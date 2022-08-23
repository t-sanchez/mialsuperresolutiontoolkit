# Copyright © 2016-2021 Medical Image Analysis Laboratory,
# University Hospital Center and University of
# Lausanne (UNIL-CHUV), Switzerland
#
#  This software is distributed under the open-source license Modified BSD.

"""Module for the preprocessing stage of the super-resolution
reconstruction pipeline.
"""

from traits.api import *
from nipype.interfaces.base import (TraitedSpec, File, InputMultiPath,
                                    OutputMultiPath, BaseInterface,
                                    BaseInterfaceInputSpec)
from nipype.interfaces import utility as util
from nipype.pipeline import engine as pe
import pymialsrtk.interfaces.preprocess as preprocess
import pymialsrtk.interfaces.utils as utils
from nipype import config


def create_preproc_stage(p_do_nlm_denoising=False, name="preproc_stage"):
    """Create a SR preprocessing workflow
    Parameters
    ----------
    ::
        name : name of workflow (default: preproc_stage)
        p_do_nlm_denoising : weither to proceed to non-local mean denoising
    Inputs::
        inputnode.input_images : Input T2w images (list of filenames)
        inputnode.input_masks : Input mask images (list of filenames)
    Outputs::
        outputnode.output_images : Processed images (list of filenames)
        outputnode.output_images_nlm : Processed images with NLM denoising,
        if p_do_nlm_denoising was set (list of filenames)
    Example
    -------
    >>> preproc_stage = create_preproc_stage(p_do_nlm_denoising=False)
    >>> preproc_stage.inputs.inputnode.input_images =
            ['sub-01_run-1_T2w.nii.gz',
             'sub-01_run-2_T2w.nii.gz']
    >>> preproc_stage.inputs.inputnode.input_masks =
            ['sub-01_run-1_T2w_mask.nii.gz',
             'sub-01_run-2_T2w_mask.nii.gz']
    >>> preproc_stage.inputs.inputnode.p_do_nlm_denoising = 'mask.nii'
    >>> preproc_stage.run() # doctest: +SKIP
    """

    preproc_stage = pe.Workflow(name=name)
    # Set up a node to define all inputs required
    # for the preprocessing workflow

    inputnode = pe.Node(
        interface=util.IdentityInterface(
            fields=['input_images', 'input_masks']),
        name='inputnode')

    output_fields = ['output_images', 'output_masks']
    if p_do_nlm_denoising:
        output_fields += ['output_images_nlm']

    outputnode = pe.Node(interface=util.IdentityInterface(fields=output_fields),
                         name='outputnode')

    reduceFOV = pe.MapNode(interface=preprocess.ReduceFieldOfView(),
                           name='reduceFOV',
                           iterfield=['input_image', 'input_mask'])

    nlmDenoise = pe.MapNode(interface=preprocess.BtkNLMDenoising(),
                            name='nlmDenoise',
                            iterfield=['in_file', 'in_mask'])

    # Sans le mask le premier correct slice intensity...
    srtkCorrectSliceIntensity01_nlm = pe.MapNode(
        interface=preprocess.MialsrtkCorrectSliceIntensity(),
        name='srtkCorrectSliceIntensity01_nlm',
        iterfield=['in_file', 'in_mask'])
    srtkCorrectSliceIntensity01_nlm.inputs.out_postfix = '_uni'

    srtkCorrectSliceIntensity01 = pe.MapNode(
        interface=preprocess.MialsrtkCorrectSliceIntensity(),
        name='srtkCorrectSliceIntensity01',
        iterfield=['in_file', 'in_mask'])
    srtkCorrectSliceIntensity01.inputs.out_postfix = '_uni'

    srtkSliceBySliceN4BiasFieldCorrection = pe.MapNode(
        interface=preprocess.MialsrtkSliceBySliceN4BiasFieldCorrection(),
        name='srtkSliceBySliceN4BiasFieldCorrection',
        iterfield=['in_file', 'in_mask'])

    srtkSliceBySliceCorrectBiasField = pe.MapNode(
        interface=preprocess.MialsrtkSliceBySliceCorrectBiasField(),
        name='srtkSliceBySliceCorrectBiasField',
        iterfield=['in_file', 'in_mask', 'in_field'])

    if p_do_nlm_denoising:
        srtkCorrectSliceIntensity02_nlm = pe.MapNode(
            interface=preprocess.MialsrtkCorrectSliceIntensity(),
            name='srtkCorrectSliceIntensity02_nlm',
            iterfield=['in_file', 'in_mask'])

        srtkIntensityStandardization01_nlm = pe.Node(
            interface=preprocess.MialsrtkIntensityStandardization(),
            name='srtkIntensityStandardization01_nlm')

        srtkHistogramNormalization_nlm = pe.Node(
            interface=preprocess.MialsrtkHistogramNormalization(),
            name='srtkHistogramNormalization_nlm')

        srtkIntensityStandardization02_nlm = pe.Node(
            interface=preprocess.MialsrtkIntensityStandardization(),
            name='srtkIntensityStandardization02_nlm')

    # 4-modules sequence to be defined as a stage.
    srtkCorrectSliceIntensity02 = pe.MapNode(
        interface=preprocess.MialsrtkCorrectSliceIntensity(),
        name='srtkCorrectSliceIntensity02',
        iterfield=['in_file', 'in_mask'])

    srtkIntensityStandardization01 = pe.Node(
        interface=preprocess.MialsrtkIntensityStandardization(),
        name='srtkIntensityStandardization01')

    srtkHistogramNormalization = pe.Node(
        interface=preprocess.MialsrtkHistogramNormalization(),
        name='srtkHistogramNormalization')

    srtkIntensityStandardization02 = pe.Node(
        interface=preprocess.MialsrtkIntensityStandardization(),
        name='srtkIntensityStandardization02')

    srtkMaskImage01 = pe.MapNode(interface=preprocess.MialsrtkMaskImage(),
                                 name='srtkMaskImage01',
                                 iterfield=['in_file', 'in_mask'])

    if p_do_nlm_denoising:
        srtkMaskImage01_nlm = pe.MapNode(
            interface=preprocess.MialsrtkMaskImage(),
            name='srtkMaskImage01_nlm',
            iterfield=['in_file', 'in_mask'])

    preproc_stage.connect(inputnode, 'input_images', reduceFOV, 'input_image')
    preproc_stage.connect(inputnode, 'input_masks', reduceFOV, 'input_mask')

    preproc_stage.connect(reduceFOV,
                          ('output_image', utils.sort_ascending),
                          nlmDenoise, 'in_file')

    preproc_stage.connect(reduceFOV,
                          ('output_mask', utils.sort_ascending),
                          nlmDenoise, 'in_mask')
    preproc_stage.connect(reduceFOV,
                          ('output_mask', utils.sort_ascending),
                          srtkCorrectSliceIntensity01_nlm, 'in_mask')
    preproc_stage.connect(reduceFOV,
                          ('output_mask', utils.sort_ascending),
                          srtkSliceBySliceN4BiasFieldCorrection, 'in_mask')
    preproc_stage.connect(reduceFOV,
                          ('output_mask', utils.sort_ascending),
                          srtkCorrectSliceIntensity01, 'in_mask')
    preproc_stage.connect(reduceFOV,
                          ('output_mask', utils.sort_ascending),
                          srtkSliceBySliceCorrectBiasField, 'in_mask')
    preproc_stage.connect(reduceFOV,
                          ('output_mask', utils.sort_ascending),
                          srtkCorrectSliceIntensity02, 'in_mask')

    preproc_stage.connect(reduceFOV,
                          ('output_mask', utils.sort_ascending),
                          srtkHistogramNormalization, "input_masks")

    preproc_stage.connect(nlmDenoise,
                          ("out_file", utils.sort_ascending),
                          srtkCorrectSliceIntensity01_nlm, "in_file")

    preproc_stage.connect(srtkCorrectSliceIntensity01_nlm,
                          ("out_file", utils.sort_ascending),
                          srtkSliceBySliceN4BiasFieldCorrection, "in_file")

    preproc_stage.connect(reduceFOV,
                          ('output_image', utils.sort_ascending),
                          srtkCorrectSliceIntensity01, 'in_file')

    preproc_stage.connect(srtkCorrectSliceIntensity01,
                          ("out_file", utils.sort_ascending),
                          srtkSliceBySliceCorrectBiasField, "in_file")
    preproc_stage.connect(srtkSliceBySliceN4BiasFieldCorrection,
                          ("out_fld_file", utils.sort_ascending),
                          srtkSliceBySliceCorrectBiasField, "in_field")

    if p_do_nlm_denoising:
        preproc_stage.connect(reduceFOV, 'output_mask',
                              srtkCorrectSliceIntensity02_nlm, 'in_mask')
        preproc_stage.connect(reduceFOV,
                              ('output_mask', utils.sort_ascending),
                              srtkHistogramNormalization_nlm, "input_masks")
        preproc_stage.connect(srtkSliceBySliceN4BiasFieldCorrection,
                              ("out_im_file", utils.sort_ascending),
                              srtkCorrectSliceIntensity02_nlm, "in_file")
        preproc_stage.connect(srtkCorrectSliceIntensity02_nlm,
                              ("out_file", utils.sort_ascending),
                              srtkIntensityStandardization01_nlm,
                              "input_images")
        preproc_stage.connect(srtkIntensityStandardization01_nlm,
                              ("output_images", utils.sort_ascending),
                              srtkHistogramNormalization_nlm, "input_images")
        preproc_stage.connect(srtkHistogramNormalization_nlm,
                              ("output_images", utils.sort_ascending),
                              srtkIntensityStandardization02_nlm,
                              "input_images")

    preproc_stage.connect(srtkSliceBySliceCorrectBiasField,
                          ("out_im_file", utils.sort_ascending),
                          srtkCorrectSliceIntensity02, "in_file")

    preproc_stage.connect(srtkCorrectSliceIntensity02, ("out_file",
                                                        utils.sort_ascending),
                          srtkIntensityStandardization01, "input_images")
    preproc_stage.connect(srtkIntensityStandardization01,
                          ("output_images", utils.sort_ascending),
                          srtkHistogramNormalization, "input_images")

    preproc_stage.connect(srtkHistogramNormalization, ("output_images",
                                                       utils.sort_ascending),
                          srtkIntensityStandardization02, "input_images")

    preproc_stage.connect(reduceFOV,
                          ("output_mask", utils.sort_ascending),
                          srtkMaskImage01, "in_mask")

    preproc_stage.connect(srtkIntensityStandardization02,
                          ("output_images", utils.sort_ascending),
                          srtkMaskImage01, "in_file")

    if p_do_nlm_denoising:
        preproc_stage.connect(srtkIntensityStandardization02_nlm,
                              ("output_images", utils.sort_ascending),
                              srtkMaskImage01_nlm, "in_file")

        preproc_stage.connect(reduceFOV,
                              ("output_mask", utils.sort_ascending),
                              srtkMaskImage01_nlm, "in_mask")

        preproc_stage.connect(srtkMaskImage01_nlm,
                              "out_im_file",
                              outputnode, 'output_images_nlm')

    preproc_stage.connect(srtkMaskImage01, "out_im_file",
                          outputnode, 'output_images')
    preproc_stage.connect(reduceFOV, "output_mask", outputnode, 'output_masks')

    return preproc_stage
