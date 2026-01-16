#!/usr/bin/env python3
# Copyright 2022 Shawn Qureshi and individual contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import requests
import os
import sys
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from . import monitor
from . import boto_setup

http_timeout = 120 # seconds

logger = monitor.getLogger()

class TimeoutHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self.timeout = http_timeout
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)

retry_strategy = Retry(
    total=10,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"],
    backoff_factor=1
)

# Make an API Call to Nexus and return json
def artifactory_http_call(args, api_path):
  """
  artifactory_http_call makes an API Call to Nexus (formerly used for Artifactory).

  :param args: arguments passed to cli command
  :param api_path: api path to add to url call
  :return: json data of the http response text
  """
  nexus_auth = (args.artifactoryuser, args.artifactorypass)
  session = requests.session()
  session.auth = nexus_auth
  session.mount("http://", TimeoutHTTPAdapter(max_retries=retry_strategy))
  session.mount("https://", TimeoutHTTPAdapter(max_retries=retry_strategy))
  
  # Add Nexus-specific headers
  session.headers.update({
    'accept': 'application/json',
    'X-Nexus-UI': 'true'
  })
  
  # Build Nexus base URL
  # Don't apply prefix for REST API paths that start with /service/rest/
  if api_path.startswith('/service/rest/'):
    prefix = ""
  elif args.artifactoryprefix:
    prefix = f"/{args.artifactoryprefix}"
  else:
    prefix = ""
  
  uri = f"{args.artifactoryprotocol}://{args.artifactoryhost}{prefix}{api_path}"

  response = session.get(uri)

  if response.status_code == 200:
    return json.loads(response.text)
  else:
    logger.critical(f"Failure connecting to {uri} : {str(response)}")
    sys.exit(1)

def artifactory_package_search(args, package, repository):
  """
  artifactory_package_search searches Nexus to verify a package exists.

  :param args: arguments passed to cli command
  :param package: package name to search for
  :param repository: repository to scan
  :return: boolean of success
  """
  # Use Nexus search endpoint
  api_path = f"/service/rest/v1/search?repository={repository}&name={package}"
  try:
    package_search = artifactory_http_call(args, api_path)
    if package_search.get('items') and len(package_search['items']) > 0:
      return True
  except SystemExit:
    pass
  return False

def artifactory_package_binary_search(args, package_dict):
  """
  artifactory_package_binary_search fetches all binaries associated with a
  package in Nexus.

  :param args: arguments passed to cli command
  :param package_dict: standard package dictionary to inspect
  :return: list of binary uri's
  """  
  
  binaries = []
  repository = package_dict['repository']
  package_name = package_dict['package'].split('/')[-1]
  
  # Use Nexus search endpoint to find components
  api_path = f"/service/rest/v1/search?repository={repository}&name={package_name}"
  
  try:
    binary_search = artifactory_http_call(args, api_path)
  except SystemExit:
    logger.info(f"No files found in Nexus for {repository} {package_dict['package']}")
    return binaries
  
  if binary_search.get('items'):
    base_url = f"{args.artifactoryprotocol}://{args.artifactoryhost}"
    if args.artifactoryprefix:
      base_url += f"/{args.artifactoryprefix}"
    
    for item in binary_search['items']:
      # Get component details
      if package_dict.get('version'):
        # Filter by version if specified
        if package_dict['version'] in item.get('version', ''):
          asset_uri = item.get('assets', [{}])[0].get('downloadUrl', '')
          if asset_uri:
            binaries.append(asset_uri)
      else:
        # Get all versions if no specific version
        asset_uri = item.get('assets', [{}])[0].get('downloadUrl', '')
        if asset_uri:
          binaries.append(asset_uri)
  else:
    logger.info(f"No files found in Nexus for {repository} {package_dict['package']}")
  
  logger.debug(f"Binaries discovered:\n{binaries}")  
  return binaries

def artifactory_binary_fetch(args, package_path, replication_path, folder):
  """
  artifactory_binary_fetch fetches all binaries associated with a
  package in Artifactory and downloads them to a subfolder.

  :param args: arguments passed to cli command
  :param package_path: uri of binary to fetch
  :param replication_path: temporary folder root to download binary to
  :param folder: subfolder to download to in replication path
  """
  artifactory_auth = (args.artifactoryuser, args.artifactorypass)

  session = requests.session()

  session.auth = (
    artifactory_auth
  )

  uri = package_path

  response = session.get(
      uri
  )

  folder_path = './' + replication_path + '/' + folder

  if not os.path.isdir(folder_path):
    os.mkdir(folder_path)

  file_path = folder_path + '/' + package_path.split('/')[-1]

  logger.debug(f"Binary Path: {file_path}")

  fd = open(file_path, 'wb')
  for chunk in response.iter_content(chunk_size=128):
      fd.write(chunk)

  if os.path.exists(file_path):
    return True
  else:
    return False

def artifactory_npm_metadata_fetch(args, package_dict):
  """
  artifactory_npm_metadata_fetch fetches specific npm metadata for a package
  in Nexus.

  :param args: arguments passed to cli command
  :param package_dict: standard package dictionary to inspect
  :return: json data of http response
  """
  # For Nexus, fetch npm package metadata via the npm registry API
  repo = package_dict['repository']
  pkg_name = package_dict['package']
  api_path = f"/{repo}/-/v1/npm/package/{pkg_name}"
  
  try:
    response = artifactory_http_call(args, api_path)
    return response
  except SystemExit:
    logger.warning(f"Could not fetch npm metadata for {pkg_name} in {repo}")
    return {}
