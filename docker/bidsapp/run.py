# Copyright © 2016-2020 Medical Image Analysis Laboratory, University Hospital Center and University of Lausanne (UNIL-CHUV), Switzerland
#
#  This software is distributed under the open-source license Modified BSD.

"""Entrypoint point script of the BIDS APP."""

import os
import sys
import json
# from traits.api import *

import multiprocessing

# Import the super-resolution pipeline
from pymialsrtk.parser import get_parser
from pymialsrtk.pipelines.anatomical.srr import AnatomicalPipeline


def return_default_nb_of_cores(nb_of_cores, openmp_proportion=2):
    """Function that returns the number of cores used by OpenMP and Nipype by default.

    Given ``openmp_proportion``, the proportion of cores dedicated to OpenMP threads,
    ``openmp_nb_of_cores`` and ``nipype_nb_of_cores`` are set by default to the following:

    .. code-block:: python

        openmp_nb_of_cores = nb_of_cores // openmp_proportion
        nipype_nb_of_cores = nb_of_cores // openmp_nb_of_cores

    where ``//`` is the integer division operator.

    Parameters
    ----------
    nb_of_cores <int>
        Number of cores available on the computer
    openmp_proportion <int>
        Proportion of cores dedicated to OpenMP threads

    Returns
    -------
    openmp_nb_of_cores <int>
        Number of cores used by default by openmp

    nipype_nb_of_cores <int>
        Number of cores used by default by openmp
    """
    openmp_nb_of_cores = nb_of_cores // openmp_proportion
    nipype_nb_of_cores = nb_of_cores // openmp_nb_of_cores

    return openmp_nb_of_cores, nipype_nb_of_cores


def check_and_return_valid_nb_of_cores(openmp_nb_of_cores, nipype_nb_of_cores, openmp_proportion=2):
    """Function that checks and returns a valid number of cores used by OpenMP and Nipype.

    If the number of cores available is exceeded by one of these variables or by the multiplication of the two,
    ``openmp_nb_of_cores`` and ``nipype_nb_of_cores`` are reset by the :func:`return_default_nb_of_cores()` to the following:

    .. code-block:: python

        openmp_nb_of_cores = nb_of_cores // 2
        nipype_nb_of_cores = nb_of_cores - openmp_nb_of_cores

    Parameters
    ----------
    openmp_nb_of_cores <int>
        Number of cores used by openmp that was initially set

    nipype_nb_of_cores <int>
        Number of cores used by Niype that was initially set

    Returns
    -------
    openmp_nb_of_cores <int>
        Valid number of cores used by openmp

    nipype_nb_of_cores <int>
        Valid number of cores used by Niype
    """
    nb_of_cores = multiprocessing.cpu_count()

    # Handles all the scenari for values of openmp_nb_of_cores and nipype_nb_of_cores
    # and make the correction if needed.
    if openmp_nb_of_cores == 0 and nipype_nb_of_cores == 0:

        openmp_nb_of_cores, nipype_nb_of_cores = return_default_nb_of_cores(nb_of_cores, openmp_proportion)

    elif openmp_nb_of_cores > 0 and nipype_nb_of_cores == 0:

        if openmp_nb_of_cores >= nb_of_cores:
            if openmp_nb_of_cores > nb_of_cores:
                print(f'WARNING: Value of {openmp_nb_of_cores} set by "--openmp_nb_of_cores" is bigger than'
                      f'the number of cores available ({nb_of_cores}) and will be reset.')
            openmp_nb_of_cores = nb_of_cores
            nipype_nb_of_cores = 1
        else:
          openmp_nb_of_cores = openmp_nb_of_cores
          nipype_nb_of_cores = nb_of_cores // openmp_nb_of_cores

    elif openmp_nb_of_cores == 0 and nipype_nb_of_cores > 0:

        if nipype_nb_of_cores >= nb_of_cores:
            if nipype_nb_of_cores > nb_of_cores:
                print(f'WARNING: Value of {nipype_nb_of_cores} set by "--nipype_nb_of_cores" is bigger than'
                      f'the number of cores available ({nb_of_cores}) and will be reset.')
            nipype_nb_of_cores = nb_of_cores
            openmp_nb_of_cores = 1
        else:
          nipype_nb_of_cores = nipype_nb_of_cores
          openmp_nb_of_cores = nb_of_cores // nipype_nb_of_cores

    elif openmp_nb_of_cores > 0 and nipype_nb_of_cores > 0:

        if nipype_nb_of_cores >= nb_of_cores:
            if openmp_nb_of_cores >= nb_of_cores:
                print(f'WARNING: Value of {nipype_nb_of_cores} and {openmp_nb_of_cores} set by "--nipype_nb_of_cores" and'
                      f'"--nipype_nb_of_cores" when multiplied are bigger than the number of cores available ({nb_of_cores})'
                      'and will be reset.')
                openmp_nb_of_cores, nipype_nb_of_cores = return_default_nb_of_cores(nb_of_cores, openmp_proportion)
            else:
                if (openmp_nb_of_cores * nipype_nb_of_cores) > nb_of_cores:
                    print(f'WARNING: Multiplication of {nipype_nb_of_cores} and {openmp_nb_of_cores} set by "--nipype_nb_of_cores" and'
                          f'"--nipype_nb_of_cores" are bigger than the number of cores available ({nb_of_cores}) and will be reset.')
                    openmp_nb_of_cores, nipype_nb_of_cores = return_default_nb_of_cores(nb_of_cores, openmp_proportion)
        else:
            if openmp_nb_of_cores >= nb_of_cores:
                print(f'WARNING: Value of {openmp_nb_of_cores} set by "--nipype_nb_of_cores" are bigger'
                      f'than the number of cores available ({nb_of_cores}) and will be reset.')
                openmp_nb_of_cores, nipype_nb_of_cores = return_default_nb_of_cores(nb_of_cores, openmp_proportion)
            else:
                if (openmp_nb_of_cores * nipype_nb_of_cores) > nb_of_cores:
                    print(f'WARNING: Multiplication of {nipype_nb_of_cores} and {openmp_nb_of_cores} set by "--nipype_nb_of_cores" and'
                          f'"--nipype_nb_of_cores" are bigger than the number of cores available ({nb_of_cores}) and will be reset.')
                    openmp_nb_of_cores, nipype_nb_of_cores = return_default_nb_of_cores(nb_of_cores, openmp_proportion)

    return openmp_nb_of_cores, nipype_nb_of_cores


def main(bids_dir, output_dir, subject, p_stacksOrder, session, paramTV=None, number_of_cores=1, srID=None,
         masks_derivatives_dir='', skip_svr=False, do_refine_hr_mask=False):
    """Main function that creates and executes the workflow of the BIDS App on one subject.

    It creates an instance of the class :class:`pymialsrtk.pipelines.anatomical.srr.AnatomicalPipeline`,
    which is then used to create and execute the workflow of the super-resolution reconstruction pipeline.

    Parameters
    ----------
    bids_dir <string>
        BIDS root directory (required)

    output_dir <string>
        Output derivatives directory (required)

    subject <string>
        Subject ID (in the form ``sub-XX``)

    p_stacks_order list<<int>>
        List of stack indices that specify the order of the stacks

    session <string>
        Session ID if applicable (in the form ``ses-YY``)

    paramTV dict <'deltatTV': float, 'lambdaTV': float, 'primal_dual_loops': int>>
        Dictionary of Total-Variation super-resolution optimizer parameters

    number_of_cores <int>
        Number of cores / CPUs used by the Nipype worflow execution engine

    srID <string>
        ID of the reconstruction useful to distinguish when multiple reconstructions
        with different order of stacks are run on the same subject

    masks_derivatives_dir <string>
        directory basename in BIDS directory derivatives where to search for masks (optional)

    """

    if paramTV is None:
        paramTV = dict()

    subject = 'sub-' + subject
    if session is not None:
        session = 'ses-' + session

    if srID is None:
        srID = "01"
    # Initialize an instance of AnatomicalPipeline
    pipeline = AnatomicalPipeline(bids_dir,
                                  output_dir,
                                  subject,
                                  p_stacksOrder,
                                  srID,
                                  session,
                                  paramTV,
                                  masks_derivatives_dir,
                                  skip_svr,
                                  do_refine_hr_mask)
    # Create the super resolution Nipype workflow
    pipeline.create_workflow()

    # Execute the workflow
    res = pipeline.run(number_of_cores=number_of_cores)

    return res


if __name__ == '__main__':

    bids_dir = os.path.join('/fetaldata')

    parser = get_parser()
    args = parser.parse_args()

    openmp_nb_of_cores = args.openmp_nb_of_cores
    nipype_nb_of_cores = args.nipype_nb_of_cores

    # Check values set for the number of cores and reset them if invalid
    openmp_nb_of_cores, nipype_nb_of_cores = check_and_return_valid_nb_of_cores(openmp_nb_of_cores,
                                                                                nipype_nb_of_cores)
    print(f'INFO: Number of cores used by Nipype engine set to {nipype_nb_of_cores}')

    os.environ['OMP_NUM_THREADS'] = str(openmp_nb_of_cores)
    print('INFO: Environment variable OMP_NUM_THREADS set to: {}'.format(os.environ['OMP_NUM_THREADS']))

    print(args.param_file)
    with open(args.param_file, 'r') as f:
        participants_params = json.load(f)
        print(participants_params)
        print(participants_params.keys())
    print()

    if len(args.participant_label) >= 1:
        for sub in args.participant_label:

            if sub in participants_params.keys():
                sr_list = participants_params[sub]
                print(sr_list)

                for sr_params in sr_list:

                    ses = sr_params["session"] if "session" in sr_params.keys() else None
                    stacks_order = sr_params['stacksOrder'] if 'stacksOrder' in sr_params.keys() else None
                    paramTV = sr_params['paramTV'] if 'paramTV' in sr_params.keys() else None
                    skip_svr = sr_params['skip_svr'] if 'skip_svr' in sr_params.keys() else False
                    do_refine_hr_mask = sr_params['do_refine_hr_mask'] if 'do_refine_hr_mask' in sr_params.keys() else False

                    if ("sr-id" not in sr_params.keys()):
                        print('Do not process subjects %s because of missing parameters.' % sub)
                        continue

                    res = main(bids_dir=args.bids_dir,
                               output_dir=args.output_dir,
                               subject=sub,
                               p_stacksOrder=stacks_order,
                               session=ses,
                               paramTV=paramTV,
                               srID=sr_params['sr-id'],
                               masks_derivatives_dir=args.masks_derivatives_dir,
                               number_of_cores=nipype_nb_of_cores,
                               skip_svr=skip_svr,
                               do_refine_hr_mask=do_refine_hr_mask)

    else:
        print('ERROR: Processing of all dataset not implemented yet\n At least one participant label should be provided')
        sys.exit(2)
