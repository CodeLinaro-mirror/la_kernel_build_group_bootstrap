# Copyright (C) 2024 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for init.py"""

import argparse
import io
import json
import unittest
import urllib.parse
from typing import Generator

from init import (KleafBootstrap, _API_ENDPOINT_PREFIX,
                  _ARTIFACT_URL_FMT, _DEFAULT_BUILD_TARGET)

# pylint: disable=protected-access


def _get_branches() -> Generator[str, None, None]:
    common_url = _API_ENDPOINT_PREFIX + "branches"

    page_token = None
    while True:
        parsed = urllib.parse.urlparse(common_url)
        query_dict = urllib.parse.parse_qs(parsed.query)
        if page_token:
            query_dict["pageToken"] = page_token
        query_dict["fields"] = "branches.name,nextPageToken"
        parsed = parsed._replace(
            query=urllib.parse.urlencode(query_dict, doseq=True))
        url = parsed.geturl()

        buf = io.BytesIO()
        KleafBootstrap._download(url, "branches", buf)
        buf.seek(0)
        json_obj = json.load(buf)
        page_token = json_obj.get("nextPageToken")
        for branch in json_obj.get("branches", []):
            yield branch["name"]

        if not page_token:
            return


def _get_supported_branches() -> Generator[str, None, None]:
    for branch in _get_branches():
        if not branch.startswith("aosp_kernel-common-android"):
            continue
        if branch == "aosp_kernel-common-android-mainline":
            yield branch
            continue
        android_release = branch.removeprefix(
            "aosp_kernel-common-android").split("-", maxsplit=1)[0]
        if not android_release.isdecimal():
            continue
        android_release = int(android_release)
        if android_release < 15:
            continue
        yield branch


class KleafBootstrapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        print("INFO: Calculating supported branches")
        cls.supported_branches = _get_supported_branches()
        return super().setUpClass()

    def test_infer_build_id(self):
        for branch in self.supported_branches:
            with self.subTest(branch=branch):
                obj = KleafBootstrap(argparse.Namespace(
                    branch=branch,
                    build_target=_DEFAULT_BUILD_TARGET,
                    build_id=None,
                    ddk_workspace=None,
                    local=None,
                    url_fmt=_ARTIFACT_URL_FMT,
                ), [])
                obj._set_build_id()
                print(f"For branch {branch}, checking {obj.build_id}")
                buf = io.BytesIO()
                obj._download_artifact("BUILD_INFO", buf)

    @unittest.skip("init_ddk.zip is not published yet")
    def test_run_with_help(self):
        for branch in self.supported_branches:
            with self.subTest(branch=branch):
                obj = KleafBootstrap(argparse.Namespace(
                    branch=branch,
                    build_target=_DEFAULT_BUILD_TARGET,
                    build_id=None,
                    url_fmt=_ARTIFACT_URL_FMT,
                ), ["-h"])
                obj.run()


if __name__ == "__main__":
    unittest.main()
