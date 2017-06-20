# Copyright 2017 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for run_deid_lib.py."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import unittest

from physionet import run_deid_lib

from mock import call
from mock import MagicMock
from mock import Mock
from mock import patch

REQUIRED_ARGS = ['--config_file', 'my_file.config',
                 '--input_pattern', 'gs://input/file-??-of-??',
                 '--output_directory', 'gs://output',
                 '--project', 'my-project',
                 '--log_directory', 'gs://logs']


class RunDeidTest(unittest.TestCase):

  def ParseArgs(self, raw_args):
    parser = argparse.ArgumentParser()
    run_deid_lib.add_all_args(parser)
    return parser.parse_args(raw_args)

  def RunPipeline(self, raw_args, storage_client=None):
    args = self.ParseArgs(raw_args)

    return run_deid_lib.run_pipeline(
        args.input_pattern, args.output_directory, args.config_file,
        args.project, args.log_directory, args.dict_directory,
        args.lists_directory, args.max_num_threads, storage_client)

  def testParseArgs(self):
    """Sanity-check for ParseArgs."""
    parsed = self.ParseArgs(REQUIRED_ARGS)
    self.assertEqual('my_file.config', parsed.config_file)

  def testInvalidInputPattern(self):
    """Program fails if --input_pattern is not as expected."""
    args = REQUIRED_ARGS[:]
    args[3] = 'gs://onlybucketname'
    self.assertEqual(1, self.RunPipeline(args))

    args[3] = 's3://not-gcs/path'
    self.assertEqual(1, self.RunPipeline(args))

  @patch('physionet.run_deid_lib.run_deid')
  def testBucketLookup(self, mock_run_deid):
    """Check that the file lookup works properly."""

    blobs = [Mock(), Mock(), Mock(), Mock()]
    # 'name' is a special keyword arg for Mock, so we have to set it like this,
    # instead of passing it to the constructor.
    blobs[0].name = 'file-00-of-02'
    blobs[1].name = 'file-01-of-02'
    blobs[2].name = 'file-02-of-02'
    blobs[3].name = 'unmatched'
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = blobs
    mock_storage_client = MagicMock()
    mock_storage_client.lookup_bucket.return_value = mock_bucket

    self.RunPipeline(REQUIRED_ARGS, mock_storage_client)

    self.assertEqual(3, mock_run_deid.call_count)
    mock_run_deid.assert_has_calls(
        [call('gs://input/file-00-of-02', 'gs://output', 'my_file.config',
              'my-project', 'gs://logs', None, None),
         call('gs://input/file-01-of-02', 'gs://output', 'my_file.config',
              'my-project', 'gs://logs', None, None),
         call('gs://input/file-02-of-02', 'gs://output', 'my_file.config',
              'my-project', 'gs://logs', None, None)])

  @patch('apiclient.discovery.build')
  @patch('oauth2client.client.GoogleCredentials.get_application_default')
  def testRunDeid(self, mock_credential_fn, mock_build_fn):
    """Test run_deid() which makes the actual call to the cloud API."""

    # Set up mocks so we can verify run() is called correctly.
    mock_credential_fn.return_value = 'fake-credentials'
    run_object = Mock()
    run_object.execute.return_value = {'done': True, 'name': 'op_name'}
    run_fn = Mock(return_value=run_object)
    mock_build_fn.return_value = Mock(
        **{'pipelines.return_value': Mock(run=run_fn)})

    # Run the pipeline.
    run_deid_lib.run_deid('infile', 'outdir', 'test.config', 'my-project-id',
                          'logdir', None, None)

    # Check that run() was called with the expected request.
    expected_request_body = {
        'pipelineArgs': {
            'projectId': 'my-project-id',
            'logging': {
                'gcsPath': 'logdir'
            }
        },
        'ephemeralPipeline': {
            'projectId': 'my-project-id',
            'docker': {
                'cmd':
                    ('gsutil cp test.config deid.config && '
                     'gsutil cp infile input.text && '
                     'perl deid.pl input deid.config && '
                     'gsutil cp input.res outdir/infile'),
                'imageName':
                    'gcr.io/genomics-api-test/physionet:latest'
            },
            'name': 'deid'
        }
    }
    run_fn.assert_called_once_with(body=expected_request_body)

if __name__ == '__main__':
  unittest.main()
