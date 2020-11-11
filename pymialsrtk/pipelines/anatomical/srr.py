# Copyright © 2016-2020 Medical Image Analysis Laboratory, University Hospital Center and University of Lausanne (UNIL-CHUV), Switzerland
#
#  This software is distributed under the open-source license Modified BSD.

"""Module for the super-resolution reconstruction pipeline."""

import os

import pkg_resources

from nipype import config, logging
# from nipype.interfaces.io import BIDSDataGrabber
from nipype.interfaces.io import DataGrabber, DataSink, JSONFileSink
from nipype.interfaces.utility import IdentityInterface
# from nipype.pipeline import Node, MapNode, Workflow
from nipype.pipeline import Node, Workflow

# Import the implemented interface from pymialsrtk
import pymialsrtk.interfaces.preprocess as preprocess
import pymialsrtk.interfaces.reconstruction as reconstruction
import pymialsrtk.interfaces.postprocess as postprocess

# Get pymialsrtk version
from pymialsrtk.info import __version__


class AnatomicalPipeline:
    """Class used to represent the workflow of the Super-Resolution reconstruction pipeline.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    output_dir <string>
        Output derivatives directory (required)

    subject <string>
        Subject ID (in the form ``sub-XX``)

    wf <nipype.pipeline.Workflow>
        Nipype workflow of the reconstruction pipeline

    dictsink <nipype.interfaces.io.JSONFileSink>
        Nipype node used to generate a JSON file that store provenance metadata
        for the SR-reconstructed images

    deltatTV <string>
        Super-resolution optimization time-step

    lambdaTV <Float>
        Regularization weight (default is 0.75)

    primal_dual_loops <string>
        Number of primal/dual loops used in the optimization of the total-variation
        super-resolution algorithm.

    srID <string>
        ID of the reconstruction useful to distinguish when multiple reconstructions
        with different order of stacks are run on the same subject

    session <string>
        Session ID if applicable (in the form ``ses-YY``)

    p_stacks_order list<<int>>
        List of stack indices that specify the order of the stacks

    use_manual_masks <Boolean>
        If set to True, use manual masks expected to be in ``/output_dir/manual_masks``.

    Examples
    --------
    >>> from pymialsrtk.pipelines.anatomical.srr import AnatomicalPipeline
    >>> # Create a new instance
    >>> pipeline = AnatomicalPipeline('/path/to/bids_dir',
                                  '/path/to/output_dir',
                                  'sub-01',
                                  [1,3,2,0],
                                  01,
                                  None,
                                  paramTV={deltatTV = "0.001",
                                           lambdaTV = "0.75",
                                           primal_dual_loops = "20"},
                                  use_manual_masks=False)
    >>> # Create the super resolution Nipype workflow
    >>> pipeline.create_workflow()
    >>> # Execute the workflow
    >>> res = pipeline.run(number_of_cores=1) # doctest: +SKIP

    """

    bids_dir = None
    output_dir = None
    subject = None
    wf = None
    dictsink = None
    deltatTV = "0.75"
    lambdaTV = "0.001"
    primal_dual_loops = "20"
    srID = "01"
    session = None
    p_stacks_order = None
    use_manual_masks = False

    def __init__(self, bids_dir, output_dir, subject,
                 p_stacks_order, srID, session=None, paramTV=None,
                 use_manual_masks=False):
        """Constructor of AnatomicalPipeline class instance."""

        # BIDS processing parameters
        self.bids_dir = bids_dir
        self.output_dir = output_dir
        self.subject = subject
        self.srID = srID
        self.session = session
        self.p_stacks_order = p_stacks_order

        # (default) sr tv parameters
        if paramTV is None:
            paramTV = dict()
        self.deltatTV = paramTV["deltatTV"] if "deltatTV" in paramTV.keys() else 0.01
        self.lambdaTV = paramTV["lambdaTV"] if "lambdaTV" in paramTV.keys() else 0.75
        self.primal_dual_loops = paramTV["primal_dual_loops"] if "primal_dual_loops" in paramTV.keys() else 10

        # Use manual/custom brain masks
        # By defaut use the automated brain extraction method
        self.use_manual_masks = use_manual_masks

    def create_workflow(self):
        """Create the Niype workflow of the super-resolution pipeline.

        It is composed of a succession of Nodes and their corresponding parameters,
        where the output of node i goes to the input of node i+1.

        """

        sub_ses = self.subject
        if self.session is not None:
            sub_ses = ''.join([sub_ses, '_', self.session])

        if self.session is None:
            wf_base_dir = os.path.join(self.output_dir,
                                       "nipype",
                                       self.subject,
                                       "rec-{}".format(self.srID))
            final_res_dir = os.path.join(self.output_dir,
                                         '-'.join(["pymialsrtk", __version__]),
                                         self.subject)
        else:
            wf_base_dir = os.path.join(self.output_dir,
                                       "nipype",
                                       self.subject,
                                       self.session,
                                       "rec-{}".format(self.srID))
            final_res_dir = os.path.join(self.output_dir,
                                         '-'.join(["pymialsrtk", __version__]),
                                         self.subject,
                                         self.session)

        # #if self.srID is not None:
        # wf_base_dir = os.path.join(wf_base_dir, self.srID)

        if not os.path.exists(wf_base_dir):
            os.makedirs(wf_base_dir)
        print("Process directory: {}".format(wf_base_dir))

        # Workflow name cannot begin with a number (oterhwise ValueError)
        pipeline_name = "srr_pipeline"

        self.wf = Workflow(name=pipeline_name,base_dir=wf_base_dir)
        # srr_nipype_dir = os.path.join(self.wf.base_dir, self.wf.name )

        # Initialization (Not sure we can control the name of nipype log)
        if os.path.isfile(os.path.join(wf_base_dir, "pypeline_" + sub_ses + ".log")):
            os.unlink(os.path.join(wf_base_dir, "pypeline_" + sub_ses + ".log"))
            # open(os.path.join(self.output_dir,"pypeline.log"), 'a').close()

        config.update_config({'logging': {'log_directory': os.path.join(wf_base_dir),
                                          'log_to_file': True},
                              'execution': {
                                  'remove_unnecessary_outputs': False,
                                  'stop_on_first_crash': True,
                                  'stop_on_first_rerun': False,
                                  'crashfile_format': "txt",
                                  'write_provenance': True},
                              'monitoring': {'enabled': True}
                              })

        config.enable_provenance()

        logging.update_logging(config)
        iflogger = logging.getLogger('nipype.interface')

        iflogger.info("**** Processing ****")

        if self.use_manual_masks:
            dg = Node(interface=DataGrabber(outfields=['T2ws', 'masks']), name='data_grabber')

            dg.inputs.base_directory = self.bids_dir
            dg.inputs.template = '*'
            dg.inputs.raise_on_empty = False
            dg.inputs.sort_filelist = True

            dg.inputs.field_template = dict(T2ws=os.path.join(self.subject, 'anat', sub_ses+'*_run-*_T2w.nii.gz'),
                                            masks=os.path.join('derivatives',
                                                               'manual_masks',
                                                               self.subject,
                                                               'anat',
                                                               sub_ses+'*_run-*_*mask.nii.gz'))
            if self.session is not None:
                dg.inputs.field_template = dict(T2ws=os.path.join(self.subject,
                                                                  self.session,
                                                                  'anat',
                                                                  '_'.join([sub_ses, '*run-*', '*T2w.nii.gz'])),
                                                masks=os.path.join('derivatives',
                                                                   'manual_masks',
                                                                   self.subject,
                                                                   self.session,
                                                                   'anat',
                                                                   '_'.join([sub_ses, '*run-*', '*mask.nii.gz'])))
            brainMask = Node(interface=IdentityInterface(fields=['masks']), name='brain_masks_bypass')

        else:

            dg = Node(interface=DataGrabber(outfields=['T2ws']), name='data_grabber')

            dg.inputs.base_directory = self.bids_dir
            dg.inputs.template = '*'
            dg.inputs.raise_on_empty = False
            dg.inputs.sort_filelist = True

            dg.inputs.field_template = dict(T2ws=os.path.join(self.subject,
                                                              'anat', sub_ses+'*_run-*_T2w.nii.gz'))
            if self.session is not None:
                dg.inputs.field_template = dict(T2ws=os.path.join(self.subject,
                                                                  self.session, 'anat', '_'.join([sub_ses, '*run-*', '*T2w.nii.gz'])))

            brainMask = Node(interface = preprocess.MultipleBrainExtraction(), name='Multiple_Brain_extraction')
            brainMask.inputs.bids_dir = self.bids_dir
            brainMask.inputs.in_ckpt_loc = pkg_resources.resource_filename("pymialsrtk",
                                                                           "data/Network_checkpoints/Network_checkpoints_localization/Unet.ckpt-88000")
            brainMask.inputs.threshold_loc = 0.49
            brainMask.inputs.in_ckpt_seg = pkg_resources.resource_filename("pymialsrtk",
                                                                           "data/Network_checkpoints/Network_checkpoints_segmentation/Unet.ckpt-20000")
            brainMask.inputs.threshold_seg = 0.5

        nlmDenoise = Node(interface=preprocess.MultipleBtkNLMDenoising(), name='nlmDenoise')
        nlmDenoise.inputs.bids_dir = self.bids_dir
        nlmDenoise.inputs.stacks_order = self.p_stacks_order

        # Sans le mask le premier correct slice intensity...
        srtkCorrectSliceIntensity01_nlm = Node(interface=preprocess.MultipleMialsrtkCorrectSliceIntensity(), name='srtkCorrectSliceIntensity01_nlm')
        srtkCorrectSliceIntensity01_nlm.inputs.bids_dir = self.bids_dir
        srtkCorrectSliceIntensity01_nlm.inputs.stacks_order = self.p_stacks_order
        srtkCorrectSliceIntensity01_nlm.inputs.out_postfix = '_uni'

        srtkCorrectSliceIntensity01 = Node(interface=preprocess.MultipleMialsrtkCorrectSliceIntensity(), name='srtkCorrectSliceIntensity01')
        srtkCorrectSliceIntensity01.inputs.bids_dir = self.bids_dir
        srtkCorrectSliceIntensity01.inputs.stacks_order = self.p_stacks_order
        srtkCorrectSliceIntensity01.inputs.out_postfix = '_uni'

        srtkSliceBySliceN4BiasFieldCorrection = Node(interface=preprocess.MultipleMialsrtkSliceBySliceN4BiasFieldCorrection(),
                                                     name='srtkSliceBySliceN4BiasFieldCorrection')
        srtkSliceBySliceN4BiasFieldCorrection.inputs.bids_dir = self.bids_dir
        srtkSliceBySliceN4BiasFieldCorrection.inputs.stacks_order = self.p_stacks_order

        srtkSliceBySliceCorrectBiasField = Node(interface=preprocess.MultipleMialsrtkSliceBySliceCorrectBiasField(), name='srtkSliceBySliceCorrectBiasField')
        srtkSliceBySliceCorrectBiasField.inputs.bids_dir = self.bids_dir
        srtkSliceBySliceCorrectBiasField.inputs.stacks_order = self.p_stacks_order

        srtkCorrectSliceIntensity02_nlm = Node(interface=preprocess.MultipleMialsrtkCorrectSliceIntensity(), name='srtkCorrectSliceIntensity02_nlm')
        srtkCorrectSliceIntensity02_nlm.inputs.bids_dir = self.bids_dir
        srtkCorrectSliceIntensity02_nlm.inputs.stacks_order = self.p_stacks_order

        srtkCorrectSliceIntensity02 = Node(interface=preprocess.MultipleMialsrtkCorrectSliceIntensity(), name='srtkCorrectSliceIntensity02')
        srtkCorrectSliceIntensity02.inputs.bids_dir = self.bids_dir
        srtkCorrectSliceIntensity02.inputs.stacks_order = self.p_stacks_order

        srtkIntensityStandardization01 = Node(interface=preprocess.MialsrtkIntensityStandardization(), name='srtkIntensityStandardization01')
        srtkIntensityStandardization01.inputs.bids_dir = self.bids_dir

        srtkIntensityStandardization01_nlm = Node(interface=preprocess.MialsrtkIntensityStandardization(), name='srtkIntensityStandardization01_nlm')
        srtkIntensityStandardization01_nlm.inputs.bids_dir = self.bids_dir

        srtkHistogramNormalization = Node(interface=preprocess.MialsrtkHistogramNormalization(), name='srtkHistogramNormalization')
        srtkHistogramNormalization.inputs.bids_dir = self.bids_dir
        srtkHistogramNormalization.inputs.stacks_order = self.p_stacks_order

        srtkHistogramNormalization_nlm = Node(interface=preprocess.MialsrtkHistogramNormalization(), name='srtkHistogramNormalization_nlm')
        srtkHistogramNormalization_nlm.inputs.bids_dir = self.bids_dir
        srtkHistogramNormalization_nlm.inputs.stacks_order = self.p_stacks_order

        srtkIntensityStandardization02 = Node(interface=preprocess.MialsrtkIntensityStandardization(), name='srtkIntensityStandardization02')
        srtkIntensityStandardization02.inputs.bids_dir = self.bids_dir

        srtkIntensityStandardization02_nlm = Node(interface=preprocess.MialsrtkIntensityStandardization(), name='srtkIntensityStandardization02_nlm')
        srtkIntensityStandardization02_nlm.inputs.bids_dir = self.bids_dir

        srtkMaskImage01 = Node(interface=preprocess.MultipleMialsrtkMaskImage(), name='srtkMaskImage01')
        srtkMaskImage01.inputs.bids_dir = self.bids_dir
        srtkMaskImage01.inputs.stacks_order = self.p_stacks_order

        srtkImageReconstruction = Node(interface=reconstruction.MialsrtkImageReconstruction(), name='srtkImageReconstruction')
        srtkImageReconstruction.inputs.bids_dir = self.bids_dir
        srtkImageReconstruction.inputs.stacks_order = self.p_stacks_order

        srtkImageReconstruction.inputs.sub_ses = sub_ses

        srtkTVSuperResolution = Node(interface=reconstruction.MialsrtkTVSuperResolution(), name='srtkTVSuperResolution')
        srtkTVSuperResolution.inputs.bids_dir = self.bids_dir
        srtkTVSuperResolution.inputs.stacks_order = self.p_stacks_order
        srtkTVSuperResolution.inputs.sub_ses = sub_ses
        srtkTVSuperResolution.inputs.in_loop = self.primal_dual_loops
        srtkTVSuperResolution.inputs.in_deltat = self.deltatTV
        srtkTVSuperResolution.inputs.in_lambda = self.lambdaTV

        srtkRefineHRMaskByIntersection = Node(interface=postprocess.MialsrtkRefineHRMaskByIntersection(), name='srtkRefineHRMaskByIntersection')
        srtkRefineHRMaskByIntersection.inputs.bids_dir = self.bids_dir
        srtkRefineHRMaskByIntersection.inputs.stacks_order = self.p_stacks_order

        srtkN4BiasFieldCorrection = Node(interface=postprocess.MialsrtkN4BiasFieldCorrection(), name='srtkN4BiasFieldCorrection')
        srtkN4BiasFieldCorrection.inputs.bids_dir = self.bids_dir

        srtkMaskImage02 = Node(interface=preprocess.MialsrtkMaskImage(), name='srtkMaskImage02')
        srtkMaskImage02.inputs.bids_dir = self.bids_dir

        datasink = Node(DataSink(), name='data_sinker')
        datasink.inputs.base_directory = final_res_dir

        # JSON file SRTV
        output_dict = {}
        output_dict["Description"] = "Isotropic high-resolution image reconstructed using the Total-Variation Super-Resolution algorithm provided by MIALSRTK"
        output_dict["Input sources run order"] = self.p_stacks_order
        output_dict["CustomMetaData"] = {}
        output_dict["CustomMetaData"]["Number of scans used"] = str(len(self.p_stacks_order))
        output_dict["CustomMetaData"]["TV regularization weight lambda"] = self.lambdaTV
        output_dict["CustomMetaData"]["Optimization time step"] = self.deltatTV
        output_dict["CustomMetaData"]["Primal/dual loops"] = self.primal_dual_loops

        self.dictsink = JSONFileSink(name='json_sinker')
        self.dictsink.inputs.in_dict = output_dict

        self.dictsink.inputs.out_file = os.path.join(final_res_dir, 'anat', sub_ses+'_rec-SR'+'_id-'+str(self.srID)+'_T2w.json')

        # Nodes ready - Linking now
        if not self.use_manual_masks:
            self.wf.connect(dg, "T2ws", brainMask, "input_images")
        else:
            self.wf.connect(dg, "masks", brainMask, "masks")

        self.wf.connect(dg, "T2ws", nlmDenoise, "input_images")
        # self.wf.connect(dg, "masks", nlmDenoise, "input_masks")  ## Comment to match docker process

        self.wf.connect(nlmDenoise, "output_images", srtkCorrectSliceIntensity01_nlm, "input_images")
        self.wf.connect(brainMask, "masks", srtkCorrectSliceIntensity01_nlm, "input_masks")

        self.wf.connect(dg, "T2ws", srtkCorrectSliceIntensity01, "input_images")
        self.wf.connect(brainMask, "masks", srtkCorrectSliceIntensity01, "input_masks")

        self.wf.connect(srtkCorrectSliceIntensity01_nlm, "output_images", srtkSliceBySliceN4BiasFieldCorrection, "input_images")
        self.wf.connect(brainMask, "masks", srtkSliceBySliceN4BiasFieldCorrection, "input_masks")

        self.wf.connect(srtkCorrectSliceIntensity01, "output_images", srtkSliceBySliceCorrectBiasField, "input_images")
        self.wf.connect(srtkSliceBySliceN4BiasFieldCorrection, "output_fields", srtkSliceBySliceCorrectBiasField, "input_fields")
        self.wf.connect(brainMask, "masks", srtkSliceBySliceCorrectBiasField, "input_masks")
        self.wf.connect(srtkSliceBySliceCorrectBiasField, "output_images", srtkCorrectSliceIntensity02, "input_images")
        self.wf.connect(brainMask, "masks", srtkCorrectSliceIntensity02, "input_masks")

        self.wf.connect(srtkSliceBySliceN4BiasFieldCorrection, "output_images", srtkCorrectSliceIntensity02_nlm, "input_images")
        self.wf.connect(brainMask, "masks", srtkCorrectSliceIntensity02_nlm, "input_masks")
        self.wf.connect(srtkCorrectSliceIntensity02, "output_images", srtkIntensityStandardization01, "input_images")

        self.wf.connect(srtkCorrectSliceIntensity02_nlm, "output_images", srtkIntensityStandardization01_nlm, "input_images")

        self.wf.connect(srtkIntensityStandardization01, "output_images", srtkHistogramNormalization, "input_images")
        self.wf.connect(brainMask, "masks", srtkHistogramNormalization, "input_masks")
        self.wf.connect(srtkIntensityStandardization01_nlm, "output_images", srtkHistogramNormalization_nlm, "input_images")
        self.wf.connect(brainMask, "masks", srtkHistogramNormalization_nlm, "input_masks")
        self.wf.connect(srtkHistogramNormalization, "output_images", srtkIntensityStandardization02, "input_images")
        self.wf.connect(srtkHistogramNormalization_nlm, "output_images", srtkIntensityStandardization02_nlm, "input_images")

        self.wf.connect(srtkIntensityStandardization02_nlm, "output_images", srtkMaskImage01, "input_images")
        self.wf.connect(brainMask, "masks", srtkMaskImage01, "input_masks")

        self.wf.connect(srtkMaskImage01, "output_images", srtkImageReconstruction, "input_images")
        self.wf.connect(brainMask, "masks", srtkImageReconstruction, "input_masks")

        self.wf.connect(srtkIntensityStandardization02, "output_images", srtkTVSuperResolution, "input_images")
        self.wf.connect(srtkImageReconstruction, "output_transforms", srtkTVSuperResolution, "input_transforms")
        self.wf.connect(brainMask, "masks", srtkTVSuperResolution, "input_masks")
        self.wf.connect(srtkImageReconstruction, "output_sdi", srtkTVSuperResolution, "input_sdi")

        self.wf.connect(srtkIntensityStandardization02, "output_images", srtkRefineHRMaskByIntersection, "input_images")
        self.wf.connect(brainMask, "masks", srtkRefineHRMaskByIntersection, "input_masks")
        self.wf.connect(srtkImageReconstruction, "output_transforms", srtkRefineHRMaskByIntersection, "input_transforms")
        self.wf.connect(srtkTVSuperResolution, "output_sr", srtkRefineHRMaskByIntersection, "input_sr")

        self.wf.connect(srtkTVSuperResolution, "output_sr", srtkN4BiasFieldCorrection, "input_image")
        self.wf.connect(srtkRefineHRMaskByIntersection, "output_srmask", srtkN4BiasFieldCorrection, "input_mask")

        self.wf.connect(srtkTVSuperResolution, "output_sr", srtkMaskImage02, "in_file")
        self.wf.connect(srtkRefineHRMaskByIntersection, "output_srmask", srtkMaskImage02, "in_mask")

        # Saving files
        substitutions = []

        for stack in self.p_stacks_order:
            print(sub_ses+'_run-'+str(stack)+'_T2w_nlm_uni_bcorr_histnorm.nii.gz',
                  '    --->     ',
                  sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_desc-preprocSDI_T2w.nii.gz')
            substitutions.append((sub_ses+'_run-'+str(stack)+'_T2w_nlm_uni_bcorr_histnorm.nii.gz',
                                 sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_desc-preprocSDI_T2w.nii.gz'))

            if not self.use_manual_masks:
                print(sub_ses+'_run-'+str(stack)+'_T2w_brainMask.nii.gz',
                      '    --->     ',
                      sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_desc-brain_mask.nii.gz')
                substitutions.append((sub_ses+'_run-'+str(stack)+'_T2w_brainMask.nii.gz',
                                     sub_ses+'_run-'+str(stack)+'_desc-brain_mask.nii.gz'))

            print(sub_ses+'_run-'+str(stack)+'_T2w_nlm_uni_bcorr_histnorm.nii.gz',
                  '    --->     ',
                  sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_desc-preprocSR_T2w.nii.gz')
            substitutions.append((sub_ses+'_run-'+str(stack)+'_T2w_uni_bcorr_histnorm.nii.gz',
                                 sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_desc-preprocSR_T2w.nii.gz'))

            print(sub_ses+'_run-'+str(stack)+'_T2w_nlm_uni_bcorr_histnorm_transform_'+str(len(self.p_stacks_order))+'V.txt',
                  '    --->     ',
                  sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_T2w_from-origin_to-SDI_mode-image_xfm.txt')
            substitutions.append((sub_ses+'_run-'+str(stack)+'_T2w_nlm_uni_bcorr_histnorm_transform_'+str(len(self.p_stacks_order))+'V.txt',
                                 sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_T2w_from-origin_to-SDI_mode-image_xfm.txt'))

            print(sub_ses+'_run-'+str(stack)+'_T2w_uni_bcorr_histnorm_LRmask.nii.gz',
                  '    --->     ',
                  sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_T2w_desc-brain_mask.nii.gz')
            substitutions.append((sub_ses+'_run-'+str(stack)+'_T2w_uni_bcorr_histnorm_LRmask.nii.gz',
                                 sub_ses+'_run-'+str(stack)+'_id-'+str(self.srID)+'_T2w_desc-brain_mask.nii.gz'))

        print('SDI_'+sub_ses+'_'+str(len(self.p_stacks_order))+'V_rad1.nii.gz',
              '    --->     ',
              sub_ses+'_rec-SDI'+'_id-'+str(self.srID)+'_T2w.nii.gz')
        substitutions.append(('SDI_'+sub_ses+'_'+str(len(self.p_stacks_order))+'V_rad1.nii.gz',
                             sub_ses+'_rec-SDI'+'_id-'+str(self.srID)+'_T2w.nii.gz'))

        print('SRTV_'+sub_ses+'_'+str(len(self.p_stacks_order))+'V_rad1_gbcorr.nii.gz',
              '    --->     ',
              sub_ses+'_rec-SR'+'_id-'+str(self.srID)+'_T2w.nii.gz')
        substitutions.append(('SRTV_'+sub_ses+'_'+str(len(self.p_stacks_order))+'V_rad1_gbcorr.nii.gz',
                             sub_ses+'_rec-SR'+'_id-'+str(self.srID)+'_T2w.nii.gz'))

        print(sub_ses+'_T2w_uni_bcorr_histnorm_srMask.nii.gz',
              '    --->     ',
              sub_ses+'_rec-SR'+'_id-'+str(self.srID)+'_T2w_desc-brain_mask.nii.gz')
        substitutions.append((sub_ses+'_T2w_uni_bcorr_histnorm_srMask.nii.gz',
                             sub_ses+'_rec-SR'+'_id-'+str(self.srID)+'_T2w_desc-brain_mask.nii.gz'))

        datasink.inputs.substitutions = substitutions

        if not self.use_manual_masks:
            self.wf.connect(brainMask, "masks", datasink, 'anat.@LRmasks')

        self.wf.connect(srtkIntensityStandardization02, "output_images", datasink, 'anat.@LRsPreproc')
        self.wf.connect(srtkMaskImage01, "output_images", datasink, 'anat.@LRsDenoised')
        self.wf.connect(srtkImageReconstruction, "output_transforms", datasink, 'xfm.@transforms')

        self.wf.connect(srtkImageReconstruction, "output_sdi", datasink, 'anat.@SDI')
        self.wf.connect(srtkN4BiasFieldCorrection, "output_image", datasink, 'anat.@SR')
        self.wf.connect(srtkRefineHRMaskByIntersection, "output_srmask", datasink, 'anat.@SRmask')

    def run(self, number_of_cores=1):
        """Execute the workflow of the super-resolution reconstruction pipeline.

        Nipype execution engine will take care of the management and execution of
        all processing steps involved in the super-resolution reconstruction pipeline.
        Note that the complete execution graph is saved as a PNG image to support
        transparency on the whole processing.

        Parameters
        ----------
        number_of_cores <int>
            Number of cores / CPUs used by the workflow

        """

        if(number_of_cores != 1):
            res = self.wf.run(plugin='MultiProc', plugin_args={'n_procs': self.number_of_cores})
            self.dictsink.run()
        else:
            res = self.wf.run()
            self.dictsink.run()

        self.wf.write_graph(dotfilename='graph.dot', graph2use='colored', format='png', simple_form=True)
        return res