#!/usr/bin/env python3
#
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

"""Downloads and run the appropriate DDK init script."""

import argparse
import io
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import BinaryIO
import urllib.error
import urllib.parse
import urllib.request

# Googlers: go/android-build-api-getting-started
_API_ENDPOINT_PREFIX = (
    "https://androidbuildinternal.googleapis.com/android/internal/build/v3/"
)
_ARTIFACT_URL_FMT = (
    _API_ENDPOINT_PREFIX
    # pylint: disable-next=line-too-long
    + "builds/{build_id}/{build_target}/attempts/latest/artifacts/{filename}/url?redirect=true"
)
_BUILD_IDS_URL_FMT = (
    _API_ENDPOINT_PREFIX
    # pylint: disable-next=line-too-long
    + "builds?branch={branch}&target={build_target}&buildAttemptStatus=complete&buildType=submitted&maxResults=1&fields=builds.buildId"
)
_DEFAULT_BUILD_TARGET = "kernel_aarch64"
_TOOLS_BAZEL = "tools/bazel"
_INIT_DDK_TARGET = "//build/kernel:init_ddk"


class KleafBootstrapError(RuntimeError):
    pass


def _resolve(opt_path: pathlib.Path | None) -> pathlib.Path | None:
    if opt_path:
        return opt_path.resolve()
    return None


class KleafBootstrap:
    """Calculates the necessary work needed to setup a DDK workspace."""

    def __init__(self, known_args: argparse.Namespace, unknown_args: list[str]):
        self.branch: str | None = known_args.branch
        self.build_id: str | None = known_args.build_id
        self.build_target: str | None = known_args.build_target
        self.ddk_workspace: pathlib.Path = _resolve(known_args.ddk_workspace)
        self.kleaf_repo: pathlib.Path | None = _resolve(known_args.kleaf_repo)
        self.local: bool = known_args.local
        self.url_fmt: str = known_args.url_fmt
        self.unknown_args = unknown_args

    @staticmethod
    def _run_script(args: list[str], cwd: str | pathlib.Path = None):
        logging.debug("Running %s from %s", args, cwd)
        subprocess.check_call(args, stderr=subprocess.STDOUT, cwd=cwd)

    def _common_args(self):
        common_args = []
        if self.build_target:
            common_args += ["--build_target", self.build_target]
        if self.kleaf_repo:
            common_args += ["--kleaf_repo", self.kleaf_repo]
        common_args += ["--url_fmt", self.url_fmt]
        common_args += ["--ddk_workspace", self.ddk_workspace]
        common_args += self.unknown_args
        return common_args

    def run(self):
        if self.local:
            args = [_TOOLS_BAZEL, "run", _INIT_DDK_TARGET]
            args += ["--", "--local"]
            args += self._common_args()
            self._run_script(args, cwd=self.kleaf_repo)
            return

        if not self.build_id:
            self._set_build_id()

        with tempfile.NamedTemporaryFile(
            prefix="init_ddk_", suffix=".zip", mode="w+b"
        ) as init_ddk:
            self._download_artifact("init_ddk.zip", init_ddk)
            args = ["python3", init_ddk.name]
            # Do not add --branch, because its meaning may change during the
            # process of this script.
            if self.build_id:
                args += ["--build_id", self.build_id]
            args += self._common_args()
            self._run_script(args)

    def _set_build_id(self) -> str:
        build_ids_fp = io.BytesIO()
        url = _BUILD_IDS_URL_FMT.format(
            branch=self.branch,
            build_target=self.build_target,
        )
        self._download(url, "build_id", build_ids_fp)
        build_ids_fp.seek(0)
        try:
            build_ids_res = json.load(
                io.TextIOWrapper(build_ids_fp, encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise KleafBootstrapError(
                "Unable to get build_id: not json"
            ) from exc

        try:
            self.build_id = build_ids_res["builds"][0]["buildId"]
        except (KeyError, IndexError) as exc:
            raise KleafBootstrapError(
                "Unable to get build_id: json not in expected format"
            ) from exc

        if not isinstance(self.build_id, str):
            raise KleafBootstrapError(
                "Unable to get build_id: json not in expected format: "
                "build id is not string"
            )

    @staticmethod
    def _download(url, remote_filename, out_f: BinaryIO):
        try:
            with urllib.request.urlopen(url) as in_f:
                logging.debug("Scheduling download for %s", remote_filename)
                shutil.copyfileobj(in_f, out_f)
        except urllib.error.URLError as exc:
            raise KleafBootstrapError(f"Fail to download {url}") from exc

    def _download_artifact(self, remote_filename, out_f: BinaryIO):
        url = self.url_fmt.format(
            build_id=self.build_id,
            build_target=self.build_target,
            filename=urllib.parse.quote(remote_filename, safe=""),  # / -> %2F
        )
        self._download(url, remote_filename, out_f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    # For every use case, one of the following is needed:
    #   --branch | --build_id for the remote use case.
    #   --local for an existing checkout (--kleaf_repo becomes required).
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--branch",
        help=(
            "Android Kernel branch from CI. e.g."
            " aosp_kernel-common-android-mainline."
        ),
        type=str,
        default=None,
    )
    group.add_argument(
        "--build_id",
        type=str,
        help="the build id to download the build for, e.g. 6148204",
        default=None,
    )
    group.add_argument(
        "--local",
        help="Whether to use a local source tree containing Kleaf.",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--build_target",
        type=str,
        help='the build target to download, e.g. "kernel_aarch64"',
        default=_DEFAULT_BUILD_TARGET,
    )
    parser.add_argument(
        "--ddk_workspace",
        help=(
            "Path for the new DDK workspace. If not specified defaults to"
            " current directory."
        ),
        type=pathlib.Path,
        default=os.getcwd(),
    )
    parser.add_argument(
        "--kleaf_repo",
        help=(
            "Path to the Kleaf source tree. Build dependencies are taken from"
            " there when --local is provided, or downloaded there otherwise."
        ),
        type=pathlib.Path,
        default=None,
    )
    parser.add_argument(
        "--url_fmt",
        help="URL format endpoint for CI downloads.",
        default=_ARTIFACT_URL_FMT,
    )
    known_args, unknown_args = parser.parse_known_args()
    # Validate pre-condition.
    if known_args.local and not known_args.kleaf_repo:
        parser.error("--local requires --kleaf_repo.")
    logging.basicConfig(
        level=logging.DEBUG, format="%(levelname)s: %(message)s"
    )

    try:
        KleafBootstrap(known_args=known_args, unknown_args=unknown_args).run()
    except KleafBootstrapError as e:
        logging.error(e, exc_info=e)
        sys.exit(1)
