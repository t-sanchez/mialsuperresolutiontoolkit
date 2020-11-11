# Copyright © 2016-2020 Medical Image Analysis Laboratory, University Hospital Center and University of Lausanne (UNIL-CHUV), Switzerland
#
#  This software is distributed under the open-source license Modified BSD.

"""PyMIALSRTK preprocessing functions.

It includes BTK Non-local-mean denoising, slice intensity correction
slice N4 bias field correction, slice-by-slice correct bias field, intensity standardization,
histogram normalization and both manual or deep learning based automatic brain extraction.

"""

import os
import traceback
from glob import glob

import nibabel
import cv2
# from medpy.io import load

import scipy.ndimage as snd
from skimage import morphology
from scipy.signal import argrelextrema

try:
    import tensorflow as tf
except ImportError:
    print("Tensorflow not available. Can not run brain extraction")

try:
    import tflearn
    # from tflearn.layers.core import input_data, dropout, fully_connected
    from tflearn.layers.conv import conv_2d, max_pool_2d, upsample_2d
except ImportError:
    print("tflearn not available. Can not run brain extraction")

import numpy as np

from traits.api import *

from nipype.utils.filemanip import split_filename
from nipype.interfaces.base import traits, \
    TraitedSpec, File, InputMultiPath, OutputMultiPath, BaseInterface, BaseInterfaceInputSpec

from pymialsrtk.interfaces.utils import run


###############
# NLM denoising
###############

class BtkNLMDenoisingInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the BtkNLMDenoising interface.

    Attributes
    ----------
    bids_dir <string>
        BIDS root directory (required)

    in_file <string>
        Input image file (required)

    in_mask <string>
        Mask of the input image

    out_postfix <string>
        suffix added to input image filename to construct output filename (default is '_nlm')

    weight <float>
        smoothing parameter (high beta produces smoother result, default is 0.1)

    See Also
    ----------
    pymialsrtk.interfaces.preprocess.BtkNLMDenoising

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    in_file = File(desc='Input image filename', mandatory=True)
    in_mask = File(desc='Input mask filename', mandatory=False)
    out_postfix = traits.Str("_nlm", desc='Suffix to be added to input image filename to construst denoised output filename', usedefault=True)
    weight = traits.Float(0.1, desc='NLM smoothing parameter (0.1 by default)', usedefault=True)


class BtkNLMDenoisingOutputSpec(TraitedSpec):
    """Class used to represent outputs of the BtkNLMDenoising interface.

    Attributes
    -----------
    out_file <string>
        Output denoised image file

    See also
    --------------
    pymialsrtk.interfaces.preprocess.BtkNLMDenoising

    """

    out_file = File(desc='Output denoised image')


class BtkNLMDenoising(BaseInterface):
    """Runs the non-local mean denoising module.

    It calls the Baby toolkit implementation by Rousseau et al. [1]_ of the method proposed by Coupé et al. [2]_.

    References
    -----------
    .. [1] Rousseau et al.; Computer Methods and Programs in Biomedicine, 2013. `(link to paper) <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3508300>`_
    .. [2] Coupé et al.; IEEE Transactions on Medical Imaging, 2008. `(link to paper) <https://doi.org/10.1109/tmi.2007.906087>`_

    Example
    ---------
    >>> from pymialsrtk.interfaces.preprocess import BtkNLMDenoising
    >>> nlmDenoise = BtkNLMDenoising()
    >>> nlmDenoise.inputs.bids_dir = '/my_directory'
    >>> nlmDenoise.inputs.in_file = 'my_image.nii.gz'
    >>> nlmDenoise.inputs.in_mask = 'my_mask.nii.gz'
    >>> nlmDenoise.inputs.weight = 0.2
    >>> nlmDenoise.run() # doctest: +SKIP

    """

    input_spec = BtkNLMDenoisingInputSpec
    output_spec = BtkNLMDenoisingOutputSpec

    def _run_interface(self, runtime):
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        out_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'),
                                ''.join((name, self.inputs.out_postfix, ext)))

        if self.inputs.in_mask:
            cmd = 'btkNLMDenoising -i "{}" -m "{}" -o "{}" -b {}'.format(self.inputs.in_file, self.inputs.in_mask, out_file, self.inputs.weight)
        else:
            cmd = 'btkNLMDenoising -i "{}" -o "{}" -b {}'.format(self.inputs.in_file, out_file, self.inputs.weight)

        try:
            print('... cmd: {}'.format(cmd))
            run(cmd, env={}, cwd=os.path.abspath(self.inputs.bids_dir))
        except Exception as e:
            print('Failed')
            print(e)
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        outputs['out_file'] = os.path.join(self.inputs.bids_dir, ''.join((name, self.inputs.out_postfix, ext)))
        return outputs


class MultipleBtkNLMDenoisingInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MultipleBtkNLMDenoising interface.

    Attributes
    ----------
    bids_dir <string>
        BIDS root directory (required)

    input_images <list<string>>
        Input image files (required)

    input_masks <list<string>>
        Masks of the input images

    out_postfix <string>
        suffix added to images files to construct output filenames (default is '_nlm')

    weight <float>
        smoothing parameter (high beta produces smoother result, default is 0.1)

    stacks_order <list<int>>
        order of images index. To ensure images are processed with their correct corresponding mask.

    See Also
    ----------
    pymialsrtk.interfaces.preprocess.MultipleBtkNLMDenoising

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='Input image filenames to be denoised', mandatory=True))
    input_masks = InputMultiPath(File(desc='Input mask filenames', mandatory=False))
    weight = traits.Float(0.1, desc='NLM smoothing parameter (0.1 by default)', usedefault=True)
    out_postfix = traits.Str("_nlm", desc='Suffix to be added to input image filenames to construst denoised output filenames',usedefault=True)
    stacks_order = traits.List(desc='Order of images index. To ensure images are processed with their correct corresponding mask', mandatory=False)


class MultipleBtkNLMDenoisingOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MultipleBtkNLMDenoising interface.

    Attributes
    -----------
    output_images list<<string>>
        Output denoised images

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleBtkNLMDenoising

    """

    output_images = OutputMultiPath(File(desc='Output denoised images'))


class MultipleBtkNLMDenoising(BaseInterface):
    """Apply the non-local mean (NLM) denoising module on multiple inputs.

    It runs for each input image the interface :class:`pymialsrtk.interfaces.preprocess.BtkNLMDenoising`
    to the NLM denoising implementation by Rousseau et al. [1]_ of the method proposed by Coupé et al. [2]_.

    References
    ------------
    .. [1] Rousseau et al.; Computer Methods and Programs in Biomedicine, 2013. `(link to paper) <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3508300>`_
    .. [2] Coupé et al.; IEEE Transactions on Medical Imaging, 2008. `(link to paper) <https://doi.org/10.1109/tmi.2007.906087>`_

    Example
    ----------
    >>> from pymialsrtk.interfaces.preprocess import MultipleBtkNLMDenoising
    >>> multiNlmDenoise = MultipleBtkNLMDenoising()
    >>> multiNlmDenoise.inputs.bids_dir = '/my_directory'
    >>> multiNlmDenoise.inputs.in_file = ['my_image01.nii.gz', 'my_image02.nii.gz']
    >>> multiNlmDenoise.inputs.in_mask = ['my_mask01.nii.gz', 'my_mask02.nii.gz']
    >>> multiNlmDenoise.stacks_order = [1,0]
    >>> multiNlmDenoise.run() # doctest: +SKIP

    See Also
    --------
    pymialsrtk.interfaces.preprocess.BtkNLMDenoising

    """

    input_spec = MultipleBtkNLMDenoisingInputSpec
    output_spec = MultipleBtkNLMDenoisingOutputSpec

    def _run_interface(self, runtime):

        # ToDo: self.inputs.stacks_order not tested
        if not self.inputs.stacks_order:
            self.inputs.stacks_order = list(range(0, len(self.inputs.input_images)))

        run_nb_images = []
        for in_file in self.inputs.input_images:
            cut_avt = in_file.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_images.append(int(cut_apr))

        if self.inputs.input_masks:
            run_nb_masks = []
            for in_mask in self.inputs.input_masks:
                cut_avt = in_mask.split('run-')[1]
                cut_apr = cut_avt.split('_')[0]
                run_nb_masks.append(int(cut_apr))

        for order in self.inputs.stacks_order:
            index_img = run_nb_images.index(order)
            if len(self.inputs.input_masks) > 0:
                index_mask = run_nb_masks.index(order)
                ax = BtkNLMDenoising(bids_dir=self.inputs.bids_dir,
                                     in_file=self.inputs.input_images[index_img],
                                     in_mask=self.inputs.input_masks[index_mask],
                                     out_postfix=self.inputs.out_postfix,
                                     weight=self.inputs.weight)
            else:
                ax = BtkNLMDenoising(bids_dir=self.inputs.bids_dir,
                                     in_file=self.inputs.input_images[index_img],
                                     out_postfix=self.inputs.out_postfix,
                                     weight=self.inputs.weight)

            ax.run()

        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['output_images'] = glob(os.path.abspath("*.nii.gz"))
        return outputs


#############################
# Slice intensity correction
#############################

class MialsrtkCorrectSliceIntensityInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MialsrtkCorrectSliceIntensity interface.

    Attributes
    ----------
    bids_dir <string>
        BIDS root directory (required)

    in_file <string>
        Input image file (required)

    in_mask <string>
        Masks of the input image

    out_postfix <string>
        suffix added to image filename to construct output filename (default is '')

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkCorrectSliceIntensity

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    in_file = File(desc='Input image filename', mandatory=True)
    in_mask = File(desc='Input mask filename', mandatory=False)
    out_postfix = traits.Str("", desc='Suffix to be added to input image file to construct corrected output filename', usedefault=True)


class MialsrtkCorrectSliceIntensityOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MialsrtkCorrectSliceIntensity interface.

    Attributes
    -----------
    out_file <string>
        Output corrected image file

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkCorrectSliceIntensity

    """

    out_file = File(desc='Output image with corrected slice intensities')


class MialsrtkCorrectSliceIntensity(BaseInterface):
    """
    Runs the MIAL SRTK mean slice intensity correction module.

    Example
    =======
    >>> from pymialsrtk.interfaces.preprocess import MialsrtkCorrectSliceIntensity
    >>> sliceIntensityCorr = MialsrtkCorrectSliceIntensity()
    >>> sliceIntensityCorr.inputs.bids_dir = '/my_directory'
    >>> sliceIntensityCorr.inputs.in_file = 'my_image.nii.gz'
    >>> sliceIntensityCorr.inputs.in_mask = 'my_mask.nii.gz'
    >>> sliceIntensityCorr.run() # doctest: +SKIP

    """

    input_spec = MialsrtkCorrectSliceIntensityInputSpec
    output_spec = MialsrtkCorrectSliceIntensityOutputSpec

    def _run_interface(self, runtime):
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        out_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_postfix, ext)))

        cmd = 'mialsrtkCorrectSliceIntensity "{}" "{}" "{}"'.format(self.inputs.in_file, self.inputs.in_mask, out_file)
        try:
            print('... cmd: {}'.format(cmd))
            run(cmd, env={}, cwd=os.path.abspath(self.inputs.bids_dir))
        except Exception as e:
            print('Failed')
            print(e)
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        outputs['out_file'] = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_postfix, ext)))
        return outputs


class MultipleMialsrtkCorrectSliceIntensityInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MultipleMialsrtkCorrectSliceIntensity interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    input_images <list<string>>
        Input image files (required)

    input_masks <list<string>>
        Masks of the input images

    out_postfix <string>
        suffix added to images files to construct output filenames (default is '')

    stacks_order <list<int>>
        order of images index. To ensure images are processed with their correct corresponding mask.

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkCorrectSliceIntensity

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='Input image filenames to be corrected for slice intensity', mandatory=True))
    input_masks = InputMultiPath(File(desc='Input mask filenames', mandatory=False))
    out_postfix = traits.Str("", desc='Suffix to be added to input image filenames to construct corrected output filenames',usedefault=True)
    stacks_order = traits.List(desc='Order of images index. To ensure images are processed with their correct corresponding mask', mandatory=False)


class MultipleMialsrtkCorrectSliceIntensityOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MultipleMialsrtkCorrectSliceIntensity interface.

    Attributes
    -----------
    output_images list<<string>>
        Output slice intensity corrected images

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkCorrectSliceIntensity

    """

    output_images = OutputMultiPath(File(desc='Output slice intensity corrected images'))


class MultipleMialsrtkCorrectSliceIntensity(BaseInterface):
    """
    Apply the MIAL SRTK slice intensity correction module on multiple images.
    Calls MialsrtkCorrectSliceIntensity interface with a list of images/masks.

    Example
    =======
    >>> from pymialsrtk.interfaces.preprocess import MultipleMialsrtkCorrectSliceIntensity
    >>> multiSliceIntensityCorr = MialsrtkCorrectSliceIntensity()
    >>> multiSliceIntensityCorr.inputs.bids_dir = '/my_directory'
    >>> multiSliceIntensityCorr.inputs.in_file = ['my_image01.nii.gz', 'my_image02.nii.gz']
    >>> multiSliceIntensityCorr.inputs.in_mask = ['my_mask01.nii.gz', 'my_mask02.nii.gz']
    >>> multiSliceIntensityCorr.run() # doctest: +SKIP

    See also
    ------------
    pymialsrtk.interfaces.preprocess.MialsrtkCorrectSliceIntensity

    """

    input_spec = MultipleMialsrtkCorrectSliceIntensityInputSpec
    output_spec = MultipleMialsrtkCorrectSliceIntensityOutputSpec

    def _run_interface(self, runtime):

        # ToDo: self.inputs.stacks_order not tested
        if not self.inputs.stacks_order:
            self.inputs.stacks_order = list(range(0, len(self.inputs.input_images)))

        run_nb_images = []
        for in_file in self.inputs.input_images:
            cut_avt = in_file.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_images.append(int(cut_apr))

        if self.inputs.input_masks:
            run_nb_masks = []
            for in_mask in self.inputs.input_masks:
                cut_avt = in_mask.split('run-')[1]
                cut_apr = cut_avt.split('_')[0]
                run_nb_masks.append(int(cut_apr))

        for order in self.inputs.stacks_order:
            index_img = run_nb_images.index(order)
            if len(self.inputs.input_masks) > 0:
                index_mask = run_nb_masks.index(order)
                ax = MialsrtkCorrectSliceIntensity(bids_dir=self.inputs.bids_dir,
                                                   in_file=self.inputs.input_images[index_img],
                                                   in_mask=self.inputs.input_masks[index_mask],
                                                   out_postfix=self.inputs.out_postfix)
            else:
                ax = MialsrtkCorrectSliceIntensity(bids_dir=self.inputs.bids_dir,
                                                   in_file=self.inputs.input_images[index_img],
                                                   out_postfix=self.inputs.out_postfix)
            ax.run()
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['output_images'] = glob(os.path.abspath("*.nii.gz"))
        return outputs


##########################################
# Slice by slice N4 bias field correction
##########################################

class MialsrtkSliceBySliceN4BiasFieldCorrectionInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MialsrtkSliceBySliceN4BiasFieldCorrection interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    in_file <string>
        Input image file (required)

    in_mask <string>
        Masks of the input image (required)

    out_im_postfix <string>
        suffix added to image filename to construct output corrected image filename (default is '_bcorr')

    out_fld_postfix <string>
        suffix added to image filename to construct output bias field image filename (default is '_n4bias')

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkSliceBySliceN4BiasFieldCorrection

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    in_file = File(desc='Input image', mandatory=True)
    in_mask = File(desc='Input mask', mandatory=True)
    out_im_postfix = traits.Str("_bcorr", desc='Suffix to be added to input image filename to construct corrected output filename', usedefault=True)
    out_fld_postfix = traits.Str("_n4bias", desc='Suffix to be added to input image filename to construct output bias field filename', usedefault=True)


class MialsrtkSliceBySliceN4BiasFieldCorrectionOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MialsrtkSliceBySliceN4BiasFieldCorrection interface.

    Attributes
    -----------
    out_im_file <string>
        Output N4 bias field corrected image file
    out_fld_file <string>
        Output bias field

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkSliceBySliceN4BiasFieldCorrection

    """

    out_im_file = File(desc='Filename of corrected output image from N4 bias field (slice by slice).')
    out_fld_file = File(desc='Filename bias field extracted slice by slice from input image.')


class MialsrtkSliceBySliceN4BiasFieldCorrection(BaseInterface):
    """Runs the MIAL SRTK slice by slice N4 bias field correction module.

    This module implements the method proposed by Tustison et al. [1]_.

    References
    ------------
    .. [1] Tustison et al.; Medical Imaging, IEEE Transactions, 2010. `(link to paper) <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3071855>`_

    Example
    ----------
    >>> from pymialsrtk.interfaces.preprocess import MialsrtkSliceBySliceN4BiasFieldCorrection
    >>> N4biasFieldCorr = MialsrtkSliceBySliceN4BiasFieldCorrection()
    >>> N4biasFieldCorr.inputs.bids_dir = '/my_directory'
    >>> N4biasFieldCorr.inputs.in_file = 'my_image.nii.gz'
    >>> N4biasFieldCorr.inputs.in_mask = 'my_mask.nii.gz'
    >>> N4biasFieldCorr.run() # doctest: +SKIP

    """

    input_spec = MialsrtkSliceBySliceN4BiasFieldCorrectionInputSpec
    output_spec = MialsrtkSliceBySliceN4BiasFieldCorrectionOutputSpec

    def _run_interface(self, runtime):
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        out_im_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_im_postfix, ext)))
        out_fld_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_fld_postfix, ext)))
        if "_uni" in out_fld_file:
            out_fld_file.replace('_uni', '')

        cmd = 'mialsrtkSliceBySliceN4BiasFieldCorrection "{}" "{}" "{}" "{}"'.format(self.inputs.in_file,
                                                                                     self.inputs.in_mask,
                                                                                     out_im_file, out_fld_file)
        try:
            print('... cmd: {}'.format(cmd))
            run(cmd, env={}, cwd=os.path.abspath(self.inputs.bids_dir))
        except Exception as e:
            print('Failed')
            print(e)
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        outputs['out_im_file'] = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_im_postfix, ext)))

        out_fld_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_fld_postfix, ext)))
        if "_uni" in out_fld_file:
            out_fld_file.replace('_uni', '')
        outputs['out_fld_file'] = out_fld_file
        return outputs


class MultipleMialsrtkSliceBySliceN4BiasFieldCorrectionInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MultipleMialsrtkSliceBySliceN4BiasFieldCorrection interface.

    Attributes
    ----------
    bids_dir <string>
        BIDS root directory (required)

    input_images <list<string>>
        Input image files (required)

    input_masks <list<string>>
        Masks of the input images (required)

    out_im_postfix <string>
        suffix added to image filename to construct output corrected image filename (default is '_bcorr')

    out_fld_postfix <string>
        suffix added to image filename to construct output bias field image filename (default is '_n4bias')

    stacks_order <list<int>>
        order of images index. To ensure images are processed with their correct corresponding mask.

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkSliceBySliceN4BiasFieldCorrection

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='files to be corrected for intensity', mandatory=True))
    input_masks = InputMultiPath(File(desc='mask of files to be corrected for intensity', mandatory=True))
    out_im_postfix = traits.Str("_bcorr", desc='Suffix to be added to input image filenames to construct corrected output filenames', usedefault=True)
    out_fld_postfix = traits.Str("_n4bias", desc='Suffix to be added to input image filenames to construct output bias field filenames', usedefault=True)
    stacks_order = traits.List(desc='Order of images index. To ensure images are processed with their correct corresponding mask', mandatory=False)


class MultipleMialsrtkSliceBySliceN4BiasFieldCorrectionOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MultipleMialsrtkSliceBySliceN4BiasFieldCorrection interface.

    Attributes
    -----------
    output_images list<<string>>
        Output N4 bias field corrected images

    output_fields list<<string>>
        Output bias fields

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkSliceBySliceN4BiasFieldCorrection

    """

    output_images = OutputMultiPath(File(desc='Output N4 bias field corrected images'))
    output_fields = OutputMultiPath(File(desc='Output bias fields'))


class MultipleMialsrtkSliceBySliceN4BiasFieldCorrection(BaseInterface):
    """Runs on multiple images the MIAL SRTK slice by slice N4 bias field correction module.

    Calls MialsrtkSliceBySliceN4BiasFieldCorrection interface that implements the method proposed by Tustison et al. [1]_ with a list of images/masks.

    References
    ------------
    .. [1] Tustison et al.; Medical Imaging, IEEE Transactions, 2010. `(link to paper) <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3071855>`_

    Example
    ----------
    >>> from pymialsrtk.interfaces.preprocess import MultipleMialsrtkSliceBySliceN4BiasFieldCorrection
    >>> multiN4biasFieldCorr = MialsrtkSliceBySliceN4BiasFieldCorrection()
    >>> multiN4biasFieldCorr.inputs.bids_dir = '/my_directory'
    >>> multiN4biasFieldCorr.inputs.in_file = ['my_image01.nii.gz', 'my_image02.nii.gz']
    >>> multiN4biasFieldCorr.inputs.in_mask = ['my_mask01.nii.gz', 'my_mask02.nii.gz']
    >>> multiN4biasFieldCorr.inputs.stacks_order = [0,1]
    >>> multiN4biasFieldCorr.run() # doctest: +SKIP

    See also
    ------------
    pymialsrtk.interfaces.preprocess.MialsrtkSliceBySliceN4BiasFieldCorrection

    """

    input_spec = MultipleMialsrtkSliceBySliceN4BiasFieldCorrectionInputSpec
    output_spec = MultipleMialsrtkSliceBySliceN4BiasFieldCorrectionOutputSpec

    def _run_interface(self, runtime):

        # ToDo: self.inputs.stacks_order not tested
        if not self.inputs.stacks_order:
            self.inputs.stacks_order = list(range(0, len(self.inputs.input_images)))

        run_nb_images = []
        for in_file in self.inputs.input_images:
            cut_avt = in_file.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_images.append(int(cut_apr))

        run_nb_masks = []
        for in_mask in self.inputs.input_masks:
            cut_avt = in_mask.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_masks.append(int(cut_apr))

        for order in self.inputs.stacks_order:
            index_img = run_nb_images.index(order)
            index_mask = run_nb_masks.index(order)

            ax = MialsrtkSliceBySliceN4BiasFieldCorrection(bids_dir=self.inputs.bids_dir,
                                                           in_file=self.inputs.input_images[index_img],
                                                           in_mask=self.inputs.input_masks[index_mask],
                                                           out_im_postfix=self.inputs.out_im_postfix,
                                                           out_fld_postfix=self.inputs.out_fld_postfix)
            ax.run()
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['output_images'] = glob(os.path.abspath(''.join(["*", self.inputs.out_im_postfix, ".nii.gz"])))
        outputs['output_fields'] = glob(os.path.abspath(''.join(["*", self.inputs.out_fld_postfix, ".nii.gz"])))
        return outputs


#####################################
# slice by slice correct bias field
#####################################

class MialsrtkSliceBySliceCorrectBiasFieldInputSpec(BaseInterfaceInputSpec):
    """Class used to represent outputs of the MialsrtkSliceBySliceCorrectBiasField interface.

    Attributes
    ----------
    bids_dir <string>
        BIDS root directory (required)

    in_file <string>
        Input image file (required)

    in_mask <string>
        Masks of the input image (required)

    in_field <string>
        Bias field to correct in the input image (required)

    out_im_postfix <string>
        suffix added to image filename to construct output corrected image filename (default is '_bcorr')

    out_fld_postfix <string>
        suffix added to image filename to construct output bias field image filename (default is '_n4bias')

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkSliceBySliceCorrectBiasField

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    in_file = File(desc='Input image', mandatory=True)
    in_mask = File(desc='Input mask', mandatory=True)
    in_field = File(desc='Input bias field', mandatory=True)
    out_im_postfix = traits.Str("_bcorr", desc='Suffixe to be added to bias field corrected in_file', usedefault=True)


class MialsrtkSliceBySliceCorrectBiasFieldOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MialsrtkSliceBySliceCorrectBiasField interface.

    Attributes
    -----------
    out_im_file <string>
        Output bias field corrected image file

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkSliceBySliceCorrectBiasField
    """

    out_im_file = File(desc='Bias field corrected image')


class MialsrtkSliceBySliceCorrectBiasField(BaseInterface):
    """Runs the MIAL SRTK independant slice by slice bias field correction module.

    Example
    =======
    >>> from pymialsrtk.interfaces.preprocess import MialsrtkSliceBySliceCorrectBiasField
    >>> biasFieldCorr = MialsrtkSliceBySliceCorrectBiasField()
    >>> biasFieldCorr.inputs.bids_dir = '/my_directory'
    >>> biasFieldCorr.inputs.in_file = 'my_image.nii.gz'
    >>> biasFieldCorr.inputs.in_mask = 'my_mask.nii.gz'
    >>> biasFieldCorr.inputs.in_field = 'my_field.nii.gz'
    >>> biasFieldCorr.run() # doctest: +SKIP

    """

    input_spec = MialsrtkSliceBySliceCorrectBiasFieldInputSpec
    output_spec = MialsrtkSliceBySliceCorrectBiasFieldOutputSpec

    def _run_interface(self, runtime):
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        out_im_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_im_postfix, ext)))

        cmd = 'mialsrtkSliceBySliceCorrectBiasField "{}" "{}" "{}" "{}"'.format(self.inputs.in_file, self.inputs.in_mask, self.inputs.in_field, out_im_file)
        try:
            print('... cmd: {}'.format(cmd))
            run(cmd, env={}, cwd=os.path.abspath(self.inputs.bids_dir))
        except Exception as e:
            print('Failed')
            print(e)
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        outputs['out_im_file'] = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_im_postfix, ext)))
        return outputs

class MultipleMialsrtkSliceBySliceCorrectBiasFieldInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MultipleMialsrtkSliceBySliceCorrectBiasField interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    input_images <list<string>>
        Input image files (required)

    input_masks <list<string>>
        Masks of the input images (required)

    input_fields <list<string>>
        Bias fields to correct in the input images (required)

    out_im_postfix <string>
        suffix added to image filename to construct output corrected image filename (default is '_bcorr')

    stacks_order <list<int>>
        order of images index. To ensure images are processed with their correct corresponding mask.

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkSliceBySliceCorrectBiasField

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='files to be corrected for intensity', mandatory=True))
    input_masks = InputMultiPath(File(desc='mask of files to be corrected for intensity', mandatory=True))
    input_fields = InputMultiPath(File(desc='field to remove', mandatory=True))
    out_im_postfix = traits.Str("_bcorr", desc='Suffixe to be added to bias field corrected input_images', usedefault=True)
    stacks_order = traits.List(desc='Order of images index. To ensure images are processed with their correct corresponding mask', mandatory=False)


class MultipleMialsrtkSliceBySliceCorrectBiasFieldOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MultipleMialsrtkSliceBySliceCorrectBiasField interface.

    Attributes
    -----------
    output_images list<<string>>
        Output bias field corrected images

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkSliceBySliceCorrectBiasField

    """

    output_images = OutputMultiPath(File(desc='Output bias field corrected images'))


class MultipleMialsrtkSliceBySliceCorrectBiasField(BaseInterface):
    """
    Runs the MIAL SRTK slice by slice bias field correction module on multiple images.

    It calls :class:`pymialsrtk.interfaces.preprocess.MialsrtkSliceBySliceCorrectBiasField` interface
    with a list of images/masks/fields.

    Example
    ----------
    >>> from pymialsrtk.interfaces.preprocess import MultipleMialsrtkSliceBySliceN4BiasFieldCorrection
    >>> multiN4biasFieldCorr = MialsrtkSliceBySliceN4BiasFieldCorrection()
    >>> multiN4biasFieldCorr.inputs.bids_dir = '/my_directory'
    >>> multiN4biasFieldCorr.inputs.in_file = ['my_image01.nii.gz', 'my_image02.nii.gz']
    >>> multiN4biasFieldCorr.inputs.in_mask = ['my_mask01.nii.gz', 'my_mask02.nii.gz']
    >>> multiN4biasFieldCorr.inputs.stacks_order = [0,1]
    >>> multiN4biasFieldCorr.run() # doctest: +SKIP

    See also
    ------------
    pymialsrtk.interfaces.preprocess.MialsrtkSliceBySliceCorrectBiasField

    """

    input_spec = MultipleMialsrtkSliceBySliceCorrectBiasFieldInputSpec
    output_spec = MultipleMialsrtkSliceBySliceCorrectBiasFieldOutputSpec

    def _run_interface(self, runtime):

        # ToDo: self.inputs.stacks_order not tested
        if not self.inputs.stacks_order:
            self.inputs.stacks_order = list(range(0, len(self.inputs.input_images)))

        run_nb_images = []
        for in_file in self.inputs.input_images:
            cut_avt = in_file.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_images.append(int(cut_apr))

        run_nb_masks = []
        for in_mask in self.inputs.input_masks:
            cut_avt = in_mask.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_masks.append(int(cut_apr))

        run_nb_fields = []
        for in_mask in self.inputs.input_fields:
            cut_avt = in_mask.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_fields.append(int(cut_apr))

        for order in self.inputs.stacks_order:
            index_img = run_nb_images.index(order)
            index_mask = run_nb_masks.index(order)
            index_fld = run_nb_fields.index(order)
            ax = MialsrtkSliceBySliceCorrectBiasField(bids_dir=self.inputs.bids_dir,
                                                      in_file=self.inputs.input_images[index_img],
                                                      in_mask=self.inputs.input_masks[index_mask],
                                                      in_field=self.inputs.input_fields[index_fld],
                                                      out_im_postfix=self.inputs.out_im_postfix)
            ax.run()
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['output_images'] = glob(os.path.abspath(''.join(["*", self.inputs.out_im_postfix, ".nii.gz"])))
        return outputs


#############################
# Intensity standardization
#############################

class MialsrtkIntensityStandardizationInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MialsrtkIntensityStandardization interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    input_images <list<string>>
        Input image filenames (required)

    in_max <float>
        Maximum intensity (default is 255)

    out_postfix <string>
        suffix added to image filenames to construct output standardized image filenames (default is '')

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkIntensityStandardization

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='files to be corrected for intensity', mandatory=True))
    out_postfix = traits.Str("", desc='Suffix to be added to intensity corrected input_images', usedefault=True)
    in_max = traits.Float(desc='Maximal intensity', usedefault=False)
    stacks_order = traits.List(desc='Order of images index. To ensure images are processed with their correct corresponding mask',
                               mandatory=False) # ToDo: Can be removed -> Also in pymialsrtk.pipelines.anatomical.srr.AnatomicalPipeline !!!


class MialsrtkIntensityStandardizationOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MialsrtkIntensityStandardization interface.

    Attributes
    -----------
    output_images list<<string>>
        Output intensity standardized images

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkIntensityStandardization

    """

    output_images = OutputMultiPath(File(desc='Images corrected for intensity'))


class MialsrtkIntensityStandardization(BaseInterface):
    """Runs the MIAL SRTK intensity standardization module.

    This module rescales image intensity by linear transformation

    Example
    =======
    >>> from pymialsrtk.interfaces.preprocess import MialsrtkIntensityStandardization
    >>> intensityStandardization= MialsrtkIntensityStandardization()
    >>> intensityStandardization.inputs.bids_dir = '/my_directory'
    >>> intensityStandardization.inputs.input_images = ['image1.nii.gz','image2.nii.gz']
    >>> intensityStandardization.run() # doctest: +SKIP

    """

    input_spec = MialsrtkIntensityStandardizationInputSpec
    output_spec = MialsrtkIntensityStandardizationOutputSpec

    def _run_interface(self, runtime):

        cmd = 'mialsrtkIntensityStandardization'
        for input_image in self.inputs.input_images:
            _, name, ext = split_filename(os.path.abspath(input_image))
            out_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_postfix, ext)))
            cmd = cmd + ' --input "{}" --output "{}"'.format(input_image, out_file)

        if self.inputs.in_max:
            cmd = cmd + ' --max "{}"'.format(self.inputs.in_max)

        try:
            print('... cmd: {}'.format(cmd))
            run(cmd, env={}, cwd=os.path.abspath(self.inputs.bids_dir))
        except Exception as e:
            print('Failed')
            print(e)
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['output_images'] = glob(os.path.abspath("*.nii.gz"))
        return outputs


###########################
# Histogram normalization
###########################

class MialsrtkHistogramNormalizationInputSpec(BaseInterfaceInputSpec):
    """Class used to represent outputs of the MialsrtkHistogramNormalization interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    input_images <list<string>>
        Input image filenames (required)

    input_masks <list<string>>
        Masks of the input images

    out_postfix <string>
        suffix added to image filenames to construct output normalized image filenames (default is '_histnorm')

    stacks_order <list<int>>
        order of images index. To ensure images are processed with their correct corresponding mask.

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkHistogramNormalization

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='Input image filenames to be normalized', mandatory=True))
    input_masks = InputMultiPath(File(desc='Input mask filenames', mandatory=False))
    out_postfix = traits.Str("_histnorm", desc='Suffix to be added to normalized input image filenames to construct ouptut normalized image filenames',
                             usedefault=True)
    stacks_order = traits.List(desc='Order of images index. To ensure images are processed with their correct corresponding mask', mandatory=False)


class MialsrtkHistogramNormalizationOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MialsrtkHistogramNormalization interface.

    Attributes
    -----------
    output_images list<<string>>
        Output histogram normalized images

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkHistogramNormalization

    """

    output_images = OutputMultiPath(File(desc='Histogram normalized images'))


class MialsrtkHistogramNormalization(BaseInterface):
    """Runs the MIAL SRTK histogram normalizaton module.

    This module implements the method proposed by Nyúl et al. [1]_.

    References
    ------------
    .. [1] Nyúl et al.; Medical Imaging, IEEE Transactions, 2000. `(link to paper) <https://ieeexplore.ieee.org/document/836373>`_

    Example
    ----------
    >>> from pymialsrtk.interfaces.preprocess import MialsrtkHistogramNormalization
    >>> histNorm = MialsrtkHistogramNormalization()
    >>> histNorm.inputs.bids_dir = '/my_directory'
    >>> histNorm.inputs.input_images = ['image1.nii.gz','image2.nii.gz']
    >>> histNorm.inputs.input_masks = ['mask1.nii.gz','mask2.nii.gz']
    >>> histNorm.inputs.out_postfix = '_histnorm'
    >>> histNorm.inputs.stacks_order = [0,1]
    >>> histNorm.run()  # doctest: +SKIP

    """

    input_spec = MialsrtkHistogramNormalizationInputSpec
    output_spec = MialsrtkHistogramNormalizationOutputSpec

    def _run_interface(self, runtime):

        cmd = 'python /usr/local/bin/mialsrtkHistogramNormalization.py '

        # ToDo: self.inputs.stacks_order not tested
        if not self.inputs.stacks_order:
            self.inputs.stacks_order = list(range(0, len(self.inputs.input_images)))

        run_nb_images = []
        for in_file in self.inputs.input_images:
            cut_avt = in_file.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_images.append(int(cut_apr))

        if self.inputs.input_masks:
            run_nb_masks = []
            for in_mask in self.inputs.input_masks:
                cut_avt = in_mask.split('run-')[1]
                cut_apr = cut_avt.split('_')[0]
                run_nb_masks.append(int(cut_apr))

        for order in self.inputs.stacks_order:
            index_img = run_nb_images.index(order)
            _, name, ext = split_filename(os.path.abspath(self.inputs.input_images[index_img]))
            out_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_postfix, ext)))
            if len(self.inputs.input_masks) > 0:
                index_mask = run_nb_masks.index(order)
                cmd = cmd + ' -i "{}" -o "{}" -m "{}" '.format(self.inputs.input_images[index_img], out_file, self.inputs.input_masks[index_mask])
            else:
                cmd = cmd + ' -i "{}" -o "{}"" '.format(self.inputs.input_images[index_img], out_file)
        try:
            print('... cmd: {}'.format(cmd))
            run(cmd, env={}, cwd=os.path.abspath(self.inputs.bids_dir))
        except Exception as e:
            print('Failed')
            print(e)

        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['output_images'] = glob(os.path.abspath(''.join(["*", self.inputs.out_postfix, ".nii.gz"])))
        return outputs


##############
# Mask Image
##############

class MialsrtkMaskImageInputSpec(BaseInterfaceInputSpec):
    """Class used to represent inputs of the MialsrtkMaskImage interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    in_file <string>
        Input image file (required)

    in_mask <string>
        Masks of the input image (required)

    out_im_postfix <string>
        suffix added to image filename to construct output masked image filename (default is '')

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkMaskImage

    """

    bids_dir = Directory(desc='BIDS root directory',mandatory=True,exists=True)
    in_file = File(desc='Input image filename to be masked',mandatory=True)
    in_mask = File(desc='Input mask filename',mandatory=True)
    out_im_postfix = traits.Str("", desc='Suffix to be added to masked in_file', usedefault=True)


class MialsrtkMaskImageOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MialsrtkMaskImage interface.

    Attributes
    -----------
    out_im_file <string>
        Output masked image

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MialsrtkMaskImage

    """

    out_im_file = File(desc='Masked image')


class MialsrtkMaskImage(BaseInterface):
    """Runs the MIAL SRTK mask image module.

    Example
    =======
    >>> from pymialsrtk.interfaces.preprocess import MialsrtkMaskImage
    >>> maskImg = MialsrtkMaskImage()
    >>> maskImg.inputs.bids_dir = '/my_directory'
    >>> maskImg.inputs.in_file = 'my_image.nii.gz'
    >>> maskImg.inputs.in_mask = 'my_mask.nii.gz'
    >>> maskImg.inputs.out_im_postfix = '_masked'
    >>> maskImg.run() # doctest: +SKIP

    """

    input_spec = MialsrtkMaskImageInputSpec
    output_spec = MialsrtkMaskImageOutputSpec

    def _run_interface(self, runtime):
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        out_im_file = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_im_postfix, ext)))

        cmd = 'mialsrtkMaskImage -i "{}" -m "{}" -o "{}"'.format(self.inputs.in_file, self.inputs.in_mask, out_im_file)
        try:
            print('... cmd: {}'.format(cmd))
            run(cmd, env={}, cwd=os.path.abspath(self.inputs.bids_dir))
        except Exception as e:
            print('Failed')
            print(e)
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        _, name, ext = split_filename(os.path.abspath(self.inputs.in_file))
        outputs['out_im_file'] = os.path.join(os.getcwd().replace(self.inputs.bids_dir, '/fetaldata'), ''.join((name, self.inputs.out_im_postfix, ext)))
        return outputs


class MultipleMialsrtkMaskImageInputSpec(BaseInterfaceInputSpec):
    """Class used to represent outputs of the MultipleMialsrtkMaskImage interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    input_images <list<string>>
        Input image files (required)

    input_masks <list<string>>
        Masks of the input images (required)

    input_fields <list<string>>
        Bias fields to correct in the input images (required)

    out_im_postfix <string>
        suffix added to image filename to construct output masked image filenames (default is '')

    stacks_order <list<int>>
        order of images index. To ensure images are processed with their correct corresponding mask.

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkMaskImage

    """

    bids_dir = Directory(desc='BIDS root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='Input image filenames to be corrected for intensity', mandatory=True))
    input_masks = InputMultiPath(File(desc='Input mask filenames ', mandatory=True))
    out_im_postfix = traits.Str("", desc='Suffix to be added to masked input_images', usedefault=True)
    stacks_order = traits.List(desc='Order of images index. To ensure images are processed with their correct corresponding mask', mandatory=False)


class MultipleMialsrtkMaskImageOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MultipleMialsrtkMaskImage interface.

    Attributes
    -----------
    output_images list<<string>>
        Output masked images

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleMialsrtkMaskImage

    """

    output_images = OutputMultiPath(File(desc='Output masked image filenames'))


class MultipleMialsrtkMaskImage(BaseInterface):
    """Runs the MIAL SRTK mask image module on multiple images.

    It calls the :class:`pymialsrtk.interfaces.preprocess.MialsrtkMaskImage` interface
    with a list of images/masks.

    Example
    =======
    >>> from pymialsrtk.interfaces.preprocess import MultipleMialsrtkMaskImage
    >>> multiMaskImg = MultipleMialsrtkMaskImage()
    >>> multiMaskImg.inputs.bids_dir = '/my_directory'
    >>> multiMaskImg.inputs.in_file = ['my_image02.nii.gz', 'my_image01.nii.gz']
    >>> multiMaskImg.inputs.in_mask = ['my_mask02.nii.gz', 'my_mask01.nii.gz']
    >>> multiMaskImg.inputs.out_im_postfix = '_masked'
    >>> multiMaskImg.inputs.stacks_order = [0,1]
    >>> multiMaskImg.run() # doctest: +SKIP

    See also
    ------------
    pymialsrtk.interfaces.preprocess.MialsrtkMaskImage

    """

    input_spec = MultipleMialsrtkMaskImageInputSpec
    output_spec = MultipleMialsrtkMaskImageOutputSpec

    def _run_interface(self, runtime):

        run_nb_images = []
        for in_file in self.inputs.input_images:
            cut_avt = in_file.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_images.append(int(cut_apr))

        run_nb_masks = []
        for in_mask in self.inputs.input_masks:
            cut_avt = in_mask.split('run-')[1]
            cut_apr = cut_avt.split('_')[0]
            run_nb_masks.append(int(cut_apr))

        for order in self.inputs.stacks_order:
            index_img = run_nb_images.index(order)
            index_mask = run_nb_masks.index(order)

            ax = MialsrtkMaskImage(bids_dir=self.inputs.bids_dir,
                                   in_file=self.inputs.input_images[index_img],
                                   in_mask=self.inputs.input_masks[index_mask],
                                   out_im_postfix=self.inputs.out_im_postfix)
            ax.run()
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['output_images'] = glob(os.path.abspath("*.nii.gz"))
        return outputs


####################
# Brain Extraction
####################


class BrainExtractionInputSpec(BaseInterfaceInputSpec):
    """Class used to represent outputs of the BrainExtraction interface.

    Attributes
    -----------
    base_dir <string>
        BIDS root directory (required)

    in_file <string>
        Input image file (required)

    in_ckpt_loc <string>
        Network_checkpoint for localization (required)

    threshold_loc <Float>
         Threshold determining cutoff probability (default is 0.49)

    in_ckpt_seg <string>
        Network_checkpoint for segmentation

    threshold_seg <Float>
         Threshold determining cutoff probability (default is 0.5)

    out_postfix <string>
        Suffix of the automatically generated mask (default is '_brainMask.nii.gz')

    See also
    --------------
    pymialsrtk.interfaces.preprocess.BrainExtraction

    """

    bids_dir = Directory(desc='Root directory', mandatory=True, exists=True)
    in_file = File(desc='Input image', mandatory=True)
    in_ckpt_loc = File(desc='Network_checkpoint for localization', mandatory=True)
    threshold_loc = traits.Float(0.49, desc='Threshold determining cutoff probability (0.49 by default)')
    in_ckpt_seg = File(desc='Network_checkpoint for segmentation', mandatory=True)
    threshold_seg = traits.Float(0.5, desc='Threshold determining cutoff probability (0.5 by default)')
    out_postfix = traits.Str("_brainMask.nii.gz", desc='Suffix of the automatically generated mask', usedefault=True)


class BrainExtractionOutputSpec(TraitedSpec):
    """Class used to represent outputs of the BrainExtraction interface.

    Attributes
    -----------
    out_file <string>
        Brain mask output image

    See also
    --------------
    pymialsrtk.interfaces.preprocess.BrainExtraction

    """

    out_file = File(desc='Brain mask image')


class BrainExtraction(BaseInterface):
    """Runs the automatic brain extraction module.

    This module is based on a 2D U-Net (Ronneberger et al. [1]_) using the pre-trained weights from Salehi et al. [2]_.

    References
    ------------
    .. [1] Ronneberger et al.; Medical Image Computing and Computer Assisted Interventions, 2015. `(link to paper) <https://arxiv.org/abs/1505.04597>`_
    .. [2] Salehi et al.; arXiv, 2017. `(link to paper) <https://arxiv.org/abs/1710.09338>`_

    Examples
    --------
    >>> from pymialsrtk.interfaces.preprocess import BrainExtraction
    >>> brainMask = BrainExtraction()
    >>> brainmask.inputs.base_dir = '/my_directory'
    >>> brainmask.inputs.in_file = 'my_image.nii.gz'
    >>> brainmask.inputs.in_ckpt_loc = 'my_loc_checkpoint'
    >>> brainmask.inputs.threshold_loc = 0.49
    >>> brainmask.inputs.in_ckpt_seg = 'my_seg_checkpoint'
    >>> brainmask.inputs.threshold_seg = 0.5
    >>> brainmask.inputs.out_postfix = '_brainMask.nii.gz'
    >>> brainmask.run() # doctest: +SKIP

    """

    input_spec = BrainExtractionInputSpec
    output_spec = BrainExtractionOutputSpec

    def _run_interface(self, runtime):

        try:
            self._extractBrain(self.inputs.in_file, self.inputs.in_ckpt_loc, self.inputs.threshold_loc,
                               self.inputs.in_ckpt_seg, self.inputs.threshold_seg, self.inputs.bids_dir, self.inputs.out_postfix)
        except Exception:
            print('Failed')
            print(traceback.format_exc())
        return runtime

    def _extractBrain(self, dataPath, modelCkptLoc, thresholdLoc, modelCkptSeg, thresholdSeg, bidsDir, out_postfix):
        """Generate a brain mask by passing the input image(s) through two networks.

        The first network localizes the brain by a coarse-grained segmentation while the
        second one segments it more precisely. The function saves the output mask in the
        specific module folder created in bidsDir

        Parameters
        ----------
        dataPath <string>
            Input image file (required)

        modelCkptLoc <string>
            Network_checkpoint for localization (required)

        thresholdLoc <Float>
             Threshold determining cutoff probability (default is 0.49)

        modelCkptSeg <string>
            Network_checkpoint for segmentation

        thresholdSeg <Float>
             Threshold determining cutoff probability (default is 0.5)

        bidsDir <string>
            BIDS root directory (required)

        out_postfix <string>
            Suffix of the automatically generated mask (default is '_brainMask.nii.gz')

        """

        ##### Step 1: Brain localization #####
        normalize = "local_max"
        width = 128
        height = 128
        border_x = 15
        border_y = 15
        n_channels = 1

        img_nib = nibabel.load(os.path.join(dataPath))
        image_data = img_nib.get_data()
        images = np.zeros((image_data.shape[2], width, height, n_channels))
        pred3dFinal = np.zeros((image_data.shape[2], image_data.shape[0], image_data.shape[1], n_channels))

        slice_counter = 0
        for ii in range(image_data.shape[2]):
           img_patch = cv2.resize(image_data[:, :, ii], dsize=(width, height), fx=width,
                                   fy=height)

           if normalize:
              if normalize == "local_max":
                 images[slice_counter, :, :, 0] = img_patch / np.max(img_patch)
              elif normalize == "global_max":
                 images[slice_counter, :, :, 0] = img_patch / max_val
              elif normalize == "mean_std":
                 images[slice_counter, :, :, 0] = (img_patch-np.mean(img_patch))/np.std(img_patch)
              else:
                 raise ValueError('Please select a valid normalization')
           else:
              images[slice_counter, :, :, 0] = img_patch

           slice_counter += 1

        # Tensorflow graph
        g = tf.Graph()
        with g.as_default():

            with tf.name_scope('inputs'):
                x = tf.placeholder(tf.float32, [None, width, height, n_channels])

            conv1 = conv_2d(x, 32, 3, activation='relu', padding='same', regularizer="L2")
            conv1 = conv_2d(conv1, 32, 3, activation='relu', padding='same', regularizer="L2")
            pool1 = max_pool_2d(conv1, 2)

            conv2 = conv_2d(pool1, 64, 3, activation='relu', padding='same', regularizer="L2")
            conv2 = conv_2d(conv2, 64, 3, activation='relu', padding='same', regularizer="L2")
            pool2 = max_pool_2d(conv2, 2)

            conv3 = conv_2d(pool2, 128, 3, activation='relu', padding='same', regularizer="L2")
            conv3 = conv_2d(conv3, 128, 3, activation='relu', padding='same', regularizer="L2")
            pool3 = max_pool_2d(conv3, 2)

            conv4 = conv_2d(pool3, 256, 3, activation='relu', padding='same', regularizer="L2")
            conv4 = conv_2d(conv4, 256, 3, activation='relu', padding='same', regularizer="L2")
            pool4 = max_pool_2d(conv4, 2)

            conv5 = conv_2d(pool4, 512, 3, activation='relu', padding='same', regularizer="L2")
            conv5 = conv_2d(conv5, 512, 3, activation='relu', padding='same', regularizer="L2")

            up6 = upsample_2d(conv5, 2)
            up6 = tflearn.layers.merge_ops.merge([up6, conv4], 'concat', axis=3)
            conv6 = conv_2d(up6, 256, 3, activation='relu', padding='same', regularizer="L2")
            conv6 = conv_2d(conv6, 256, 3, activation='relu', padding='same', regularizer="L2")

            up7 = upsample_2d(conv6, 2)
            up7 = tflearn.layers.merge_ops.merge([up7, conv3], 'concat', axis=3)
            conv7 = conv_2d(up7, 128, 3, activation='relu', padding='same', regularizer="L2")
            conv7 = conv_2d(conv7, 128, 3, activation='relu', padding='same', regularizer="L2")

            up8 = upsample_2d(conv7, 2)
            up8 = tflearn.layers.merge_ops.merge([up8, conv2], 'concat', axis=3)
            conv8 = conv_2d(up8, 64, 3, activation='relu', padding='same', regularizer="L2")
            conv8 = conv_2d(conv8, 64, 3, activation='relu', padding='same', regularizer="L2")

            up9 = upsample_2d(conv8, 2)
            up9 = tflearn.layers.merge_ops.merge([up9, conv1], 'concat', axis=3)
            conv9 = conv_2d(up9, 32, 3, activation='relu', padding='same', regularizer="L2")
            conv9 = conv_2d(conv9, 32, 3, activation='relu', padding='same', regularizer="L2")

            pred = conv_2d(conv9, 2, 1,  activation='linear', padding='valid')

        # Thresholding parameter to binarize predictions
        percentileLoc = thresholdLoc*100

        im = np.zeros((1, width, height, n_channels))
        pred3d = []
        with tf.Session(graph=g) as sess_test_loc:
            # Restore the model
            tf_saver = tf.train.Saver()
            tf_saver.restore(sess_test_loc, modelCkptLoc)

            for idx in range(images.shape[0]):

                im = np.reshape(images[idx, :, :, :], [1, width, height, n_channels])

                feed_dict = {x: im}
                pred_ = sess_test_loc.run(pred, feed_dict=feed_dict)

                theta = np.percentile(pred_, percentileLoc)
                pred_bin = np.where(pred_ > theta, 1, 0)
                pred3d.append(pred_bin[0, :, :, 0].astype('float64'))

            #####
            pred3d = np.asarray(pred3d)
            heights = []
            widths = []
            coms_x = []
            coms_y = []

            # Apply PPP
            ppp = True
            if ppp:
                pred3d = self._post_processing(pred3d)

            pred3d = [cv2.resize(elem,dsize=(image_data.shape[1], image_data.shape[0]), interpolation=cv2.INTER_NEAREST) for elem in pred3d]
            pred3d = np.asarray(pred3d)
            for i in range(np.asarray(pred3d).shape[0]):
                if np.sum(pred3d[i, :, :]) != 0:
                    pred3d[i, :, :] = self._extractLargestCC(pred3d[i, :, :].astype('uint8'))
                    contours, _ = cv2.findContours(pred3d[i, :, :].astype('uint8'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    area = cv2.minAreaRect(np.squeeze(contours))
                    heights.append(area[1][0])
                    widths.append(area[1][1])
                    bbox = cv2.boxPoints(area).astype('int')
                    coms_x.append(int((np.max(bbox[:, 1])+np.min(bbox[:, 1]))/2))
                    coms_y.append(int((np.max(bbox[:, 0])+np.min(bbox[:, 0]))/2))
            # Saving localization points
            med_x = int(np.median(coms_x))
            med_y = int(np.median(coms_y))
            half_max_x = int(np.max(heights)/2)
            half_max_y = int(np.max(widths)/2)
            x_beg = med_x-half_max_x-border_x
            x_end = med_x+half_max_x+border_x
            y_beg = med_y-half_max_y-border_y
            y_end = med_y+half_max_y+border_y

        ##### Step 2: Brain segmentation #####
        width = 96
        height = 96

        images = np.zeros((image_data.shape[2], width, height, n_channels))

        slice_counter = 0
        for ii in range(image_data.shape[2]):
            img_patch = cv2.resize(image_data[x_beg:x_end, y_beg:y_end, ii], dsize=(width, height))

            if normalize:
                if normalize == "local_max":
                    images[slice_counter, :, :, 0] = img_patch / np.max(img_patch)
                elif normalize == "mean_std":
                    images[slice_counter, :, :, 0] = (img_patch-np.mean(img_patch))/np.std(img_patch)
                else:
                    raise ValueError('Please select a valid normalization')
            else:
                images[slice_counter, :, :, 0] = img_patch

            slice_counter += 1

        g = tf.Graph()
        with g.as_default():

            with tf.name_scope('inputs'):
                x = tf.placeholder(tf.float32, [None, width, height, n_channels])

            conv1 = conv_2d(x, 32, 3, activation='relu', padding='same', regularizer="L2")
            conv1 = conv_2d(conv1, 32, 3, activation='relu', padding='same', regularizer="L2")
            pool1 = max_pool_2d(conv1, 2)

            conv2 = conv_2d(pool1, 64, 3, activation='relu', padding='same', regularizer="L2")
            conv2 = conv_2d(conv2, 64, 3, activation='relu', padding='same', regularizer="L2")
            pool2 = max_pool_2d(conv2, 2)

            conv3 = conv_2d(pool2, 128, 3, activation='relu', padding='same', regularizer="L2")
            conv3 = conv_2d(conv3, 128, 3, activation='relu', padding='same', regularizer="L2")
            pool3 = max_pool_2d(conv3, 2)

            conv4 = conv_2d(pool3, 256, 3, activation='relu', padding='same', regularizer="L2")
            conv4 = conv_2d(conv4, 256, 3, activation='relu', padding='same', regularizer="L2")
            pool4 = max_pool_2d(conv4, 2)

            conv5 = conv_2d(pool4, 512, 3, activation='relu', padding='same', regularizer="L2")
            conv5 = conv_2d(conv5, 512, 3, activation='relu', padding='same', regularizer="L2")

            up6 = upsample_2d(conv5, 2)
            up6 = tflearn.layers.merge_ops.merge([up6, conv4], 'concat',axis=3)
            conv6 = conv_2d(up6, 256, 3, activation='relu', padding='same', regularizer="L2")
            conv6 = conv_2d(conv6, 256, 3, activation='relu', padding='same', regularizer="L2")

            up7 = upsample_2d(conv6, 2)
            up7 = tflearn.layers.merge_ops.merge([up7, conv3],'concat', axis=3)
            conv7 = conv_2d(up7, 128, 3, activation='relu', padding='same', regularizer="L2")
            conv7 = conv_2d(conv7, 128, 3, activation='relu', padding='same', regularizer="L2")

            up8 = upsample_2d(conv7, 2)
            up8 = tflearn.layers.merge_ops.merge([up8, conv2],'concat', axis=3)
            conv8 = conv_2d(up8, 64, 3, activation='relu', padding='same', regularizer="L2")
            conv8 = conv_2d(conv8, 64, 3, activation='relu', padding='same', regularizer="L2")

            up9 = upsample_2d(conv8, 2)
            up9 = tflearn.layers.merge_ops.merge([up9, conv1],'concat', axis=3)
            conv9 = conv_2d(up9, 32, 3, activation='relu', padding='same', regularizer="L2")
            conv9 = conv_2d(conv9, 32, 3, activation='relu', padding='same', regularizer="L2")

            pred = conv_2d(conv9, 2, 1,  activation='linear', padding='valid')

        with tf.Session(graph=g) as sess_test_seg:
            # Restore the model
            tf_saver = tf.train.Saver()
            tf_saver.restore(sess_test_seg, modelCkptSeg)

            for idx in range(images.shape[0]):

                im = np.reshape(images[idx, :, :], [1, width, height, n_channels])
                feed_dict = {x: im}
                pred_ = sess_test_seg.run(pred, feed_dict=feed_dict)
                percentileSeg = thresholdSeg * 100
                theta = np.percentile(pred_, percentileSeg)
                pred_bin = np.where(pred_ > theta, 1, 0)
                # Map predictions to original indices and size
                pred_bin = cv2.resize(pred_bin[0, :, :, 0], dsize=(y_end-y_beg, x_end-x_beg), interpolation=cv2.INTER_NEAREST)
                pred3dFinal[idx, x_beg:x_end, y_beg:y_end,0] = pred_bin.astype('float64')

            pppp = True
            if pppp:
                pred3dFinal = self._post_processing(np.asarray(pred3dFinal))
            pred3d = [cv2.resize(elem, dsize=(image_data.shape[1], image_data.shape[0]), interpolation=cv2.INTER_NEAREST) for elem in pred3dFinal]
            pred3d = np.asarray(pred3d)
            upsampled = np.swapaxes(np.swapaxes(pred3d,1,2),0,2) #if Orient module applied, no need for this line(?)
            up_mask = nibabel.Nifti1Image(upsampled,img_nib.affine)
            # Save output mask
            _, name, ext = split_filename(os.path.abspath(dataPath))
            save_file = os.path.join(os.getcwd().replace(bidsDir, '/fetaldata'), ''.join((name, out_postfix, ext)))
            nibabel.save(up_mask, save_file)

    def _extractLargestCC(self, image):
        """Function returning largest connected component of an object."""

        nb_components, output, stats, _ = cv2.connectedComponentsWithStats(image, connectivity=4)
        sizes = stats[:, -1]
        max_label = 1
        # in case no segmentation
        if len(sizes) < 2:
            return image
        max_size = sizes[1]
        for i in range(2, nb_components):
            if sizes[i] > max_size:
                max_label = i
                max_size = sizes[i]
        largest_cc = np.zeros(output.shape)
        largest_cc[output == max_label] = 255
        return largest_cc.astype('uint8')

    def _post_processing(self, pred_lbl):
        """Post-processing the binarized network output by Priscille de Dumast."""

        # post_proc = True
        post_proc_cc = True
        post_proc_fill_holes = True

        post_proc_closing_minima = True
        post_proc_opening_maxima = True
        post_proc_extremity = False
        # stackmodified = True

        crt_stack = pred_lbl.copy()
        crt_stack_pp = crt_stack.copy()

        if 1:

            distrib = []
            for iSlc in range(crt_stack.shape[0]):
                distrib.append(np.sum(crt_stack[iSlc]))

            if post_proc_cc:
                # print("post_proc_cc")
                crt_stack_cc = crt_stack.copy()
                labeled_array, _ = snd.measurements.label(crt_stack_cc)
                unique, counts = np.unique(labeled_array, return_counts=True)

                # Try to remove false positives seen as independent connected components #2ndBrain
                for ind, _ in enumerate(unique):
                    if 5 < counts[ind] and counts[ind] < 300:
                        wherr = np.where(labeled_array == unique[ind])
                        for ii in range(len(wherr[0])):
                            crt_stack_cc[wherr[0][ii], wherr[1][ii], wherr[2][ii]] = 0

                crt_stack_pp = crt_stack_cc.copy()

            if post_proc_fill_holes:
                # print("post_proc_fill_holes")
                crt_stack_holes = crt_stack_pp.copy()

                inv_mask = 1 - crt_stack_holes
                labeled_holes, _ = snd.measurements.label(inv_mask)
                unique, counts = np.unique(labeled_holes, return_counts=True)

                for lbl in unique[2:]:
                    trou = np.where(labeled_holes == lbl)
                    for ind in range(len(trou[0])):
                        inv_mask[trou[0][ind], trou[1][ind], trou[2][ind]] = 0

                crt_stack_holes = 1 - inv_mask
                crt_stack_cc = crt_stack_holes.copy()
                crt_stack_pp = crt_stack_holes.copy()

                distrib_cc = []
                for iSlc in range(crt_stack_pp.shape[0]):
                    distrib_cc.append(np.sum(crt_stack_pp[iSlc]))

            if post_proc_closing_minima or post_proc_opening_maxima:

                if 0:  # closing GLOBAL
                    crt_stack_closed_minima = crt_stack_pp.copy()
                    crt_stack_closed_minima = morphology.binary_closing(crt_stack_closed_minima)
                    crt_stack_pp = crt_stack_closed_minima.copy()

                    distrib_closed = []
                    for iSlc in range(crt_stack_closed_minima.shape[0]):
                        distrib_closed.append(np.sum(crt_stack_closed_minima[iSlc]))

                if post_proc_closing_minima:
                    # if 0:
                    crt_stack_closed_minima = crt_stack_pp.copy()

                    # for local minima
                    local_minima = argrelextrema(np.asarray(distrib_cc), np.less)[0]
                    local_maxima = argrelextrema(np.asarray(distrib_cc), np.greater)[0]

                    for iMin, _ in enumerate(local_minima):
                        for iMax in range(len(local_maxima) - 1):
                            # print(local_maxima[iMax], "<", local_minima[iMin], "AND", local_minima[iMin], "<", local_maxima[iMax+1], "   ???")

                            # find between which maxima is the minima localized
                            if local_maxima[iMax] < local_minima[iMin] and local_minima[iMin] < local_maxima[iMax + 1]:

                                # check if diff max-min is large enough to be considered
                                if ((distrib_cc[local_maxima[iMax]] - distrib_cc[local_minima[iMin]] > 50) and
                                   (distrib_cc[local_maxima[iMax + 1]] - distrib_cc[local_minima[iMin]] > 50)):
                                    sub_stack = crt_stack_closed_minima[local_maxima[iMax] - 1:local_maxima[iMax + 1] + 1, :, :]

                                    # print("We did 3d close.")
                                    sub_stack = morphology.binary_closing(sub_stack)
                                    crt_stack_closed_minima[local_maxima[iMax] - 1:local_maxima[iMax + 1] + 1, :, :] = sub_stack

                    crt_stack_pp = crt_stack_closed_minima.copy()

                    distrib_closed = []
                    for iSlc in range(crt_stack_closed_minima.shape[0]):
                        distrib_closed.append(np.sum(crt_stack_closed_minima[iSlc]))

                if post_proc_opening_maxima:
                    crt_stack_opened_maxima = crt_stack_pp.copy()

                    local = True
                    if local:
                        local_maxima_n = argrelextrema(np.asarray(distrib_closed), np.greater)[
                            0]  # default is mode='clip'. Doesn't consider extremity as being an extrema

                        for iMax, _ in enumerate(local_maxima_n):

                            # Check if this local maxima is a "peak"
                            if ((distrib[local_maxima_n[iMax]] - distrib[local_maxima_n[iMax] - 1] > 50) and
                               (distrib[local_maxima_n[iMax]] - distrib[local_maxima_n[iMax] + 1] > 50)):

                                if 0:
                                    print("Ceci est un pic de au moins 50.", distrib[local_maxima_n[iMax]], "en",
                                          local_maxima_n[iMax])
                                    print("                                bordé de", distrib[local_maxima_n[iMax] - 1],
                                          "en", local_maxima_n[iMax] - 1)
                                    print("                                et", distrib[local_maxima_n[iMax] + 1], "en",
                                          local_maxima_n[iMax] + 1)
                                    print("")

                                sub_stack = crt_stack_opened_maxima[local_maxima_n[iMax] - 1:local_maxima_n[iMax] + 2, :, :]
                                sub_stack = morphology.binary_opening(sub_stack)
                                crt_stack_opened_maxima[local_maxima_n[iMax] - 1:local_maxima_n[iMax] + 2, :, :] = sub_stack
                    else:
                        crt_stack_opened_maxima = morphology.binary_opening(crt_stack_opened_maxima)

                    crt_stack_pp = crt_stack_opened_maxima.copy()

                    distrib_opened = []
                    for iSlc in range(crt_stack_pp.shape[0]):
                        distrib_opened.append(np.sum(crt_stack_pp[iSlc]))

                if post_proc_extremity:

                    crt_stack_extremity = crt_stack_pp.copy()

                    # check si y a un maxima sur une extremite
                    maxima_extrema = argrelextrema(np.asarray(distrib_closed), np.greater, mode='wrap')[0]
                    # print("maxima_extrema", maxima_extrema, "     numslices",numslices, "     numslices-1",numslices-1)

                    if distrib_opened[0] - distrib_opened[1] > 40:
                        # print("First slice of ", distrib_opened, " is a maxima")
                        sub_stack = crt_stack_extremity[0:2, :, :]
                        sub_stack = morphology.binary_opening(sub_stack)
                        crt_stack_extremity[0:2, :, :] = sub_stack
                        # print("On voulait close 1st slices",  sub_stack.shape[0])

                    if pred_lbl.shape[0] - 1 in maxima_extrema:
                        # print(numslices-1, "in maxima_extrema", maxima_extrema )

                        sub_stack = crt_stack_opened_maxima[-2:, :, :]
                        sub_stack = morphology.binary_opening(sub_stack)
                        crt_stack_opened_maxima[-2:, :, :] = sub_stack

                        # print("On voulait close last slices",  sub_stack.shape[0])

                    crt_stack_pp = crt_stack_extremity.copy()

                    distrib_opened_border = []
                    for iSlc in range(crt_stack_pp.shape[0]):
                        distrib_opened_border.append(np.sum(crt_stack_pp[iSlc]))

        return crt_stack_pp

    def _list_outputs(self):

        return {'out_file': self.inputs.in_file[:-4] + self.inputs.out_postfix}


class MultipleBrainExtractionInputSpec(BaseInterfaceInputSpec):
    """Class used to represent outputs of the MultipleBrainExtraction interface.

    Attributes
    -----------
    bids_dir <string>
        BIDS root directory (required)

    input_images list<<string>>
        List of input image file (required)

    in_ckpt_loc <string>
        Network_checkpoint for localization (required)

    threshold_loc <Float>
         Threshold determining cutoff probability (default is 0.49)

    in_ckpt_seg <string>
        Network_checkpoint for segmentation

    threshold_seg <Float>
         Threshold determining cutoff probability (default is 0.5)

    out_postfix <string>
        Suffix of the automatically generated mask (default is '_brainMask')

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleBrainExtraction

    """

    bids_dir = Directory(desc='Root directory', mandatory=True, exists=True)
    input_images = InputMultiPath(File(desc='MRI Images', mandatory=True))
    in_ckpt_loc = File(desc='Network_checkpoint for localization', mandatory=True)
    threshold_loc = traits.Float(0.49, desc='Threshold determining cutoff probability (0.49 by default)')
    in_ckpt_seg = File(desc='Network_checkpoint for segmentation', mandatory=True)
    threshold_seg = traits.Float(0.5, desc='Threshold determining cutoff probability (0.5 by default)')
    out_postfix = traits.Str("_brainMask", desc='Suffixe of the automatically generated mask', usedefault=True)


class MultipleBrainExtractionOutputSpec(TraitedSpec):
    """Class used to represent outputs of the MultipleBrainExtraction interface.

    Attributes
    -----------
    output_images list<<string>>
        Output masks

    See also
    --------------
    pymialsrtk.interfaces.preprocess.MultipleBrainExtraction

    """

    masks = OutputMultiPath(File(desc='Output masks'))


class MultipleBrainExtraction(BaseInterface):
    """Runs on multiple images the automatic brain extraction module.

    It calls on a list of images the :class:`pymialsrtk.interfaces.preprocess.BrainExtraction.BrainExtraction` module
    that implements a brain extraction algorithm based on a 2D U-Net (Ronneberger et al. [1]_) using
    the pre-trained weights from Salehi et al. [2]_.

    References
    ------------
    .. [1] Ronneberger et al.; Medical Image Computing and Computer Assisted Interventions, 2015. `(link to paper) <https://arxiv.org/abs/1505.04597>`_
    .. [2] Salehi et al.; arXiv, 2017. `(link to paper) <https://arxiv.org/abs/1710.09338>`_

    See also
    ------------
    pymialsrtk.interfaces.preprocess.BrainExtraction

    """

    input_spec = MultipleBrainExtractionInputSpec
    output_spec = MultipleBrainExtractionOutputSpec

    def _run_interface(self, runtime):
        if len(self.inputs.input_images) > 0:
            for input_image in self.inputs.input_images:
                ax = BrainExtraction(bids_dir=self.inputs.bids_dir,
                                     in_file=input_image,
                                     in_ckpt_loc=self.inputs.in_ckpt_loc,
                                     threshold_loc=self.inputs.threshold_loc,
                                     in_ckpt_seg=self.inputs.in_ckpt_seg,
                                     threshold_seg=self.inputs.threshold_seg,
                                     out_postfix=self.inputs.out_postfix)
                ax.run()
        return runtime

    def _list_outputs(self):
        outputs = self._outputs().get()
        outputs['masks'] = glob(os.path.abspath("*.nii.gz"))
        return outputs