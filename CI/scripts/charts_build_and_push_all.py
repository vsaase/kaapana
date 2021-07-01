#!/usr/bin/env python3
import sys
import glob
import os
import json
from subprocess import PIPE, run

import getpass
from shutil import copyfile
from argparse import ArgumentParser
from time import time
from pathlib import Path

suite_tag = "Helm Charts"

build_ready_list = None


def get_timestamp():
    return str(int(time() * 1000))


def check_helm_installed():
    command = ["helm", "push", "--help"]
    output = run(command, stdout=PIPE, stderr=PIPE,
                 universal_newlines=True, timeout=10)

    if output.returncode != 0 or "The Kubernetes package manager" in output.stdout:
        print("Helm ist not installed correctly!")
        print("Make sure Helm > v3 and the 'push'-plugin is installed!")
        print("hint: helm plugin install https://github.com/chartmuseum/helm-push")
        exit(1)

    command = ["helm", "kubeval", "--help"]
    output = run(command, stdout=PIPE, stderr=PIPE,
                 universal_newlines=True, timeout=3)

    if output.returncode != 0 or "The Kubernetes package manager" in output.stdout:
        print("Helm kubeval ist not installed correctly!")
        print("Make sure Helm kubeval-plugin is installed!")
        print("hint: helm plugin install https://github.com/instrumenta/helm-kubeval")
        exit(1)


def make_log(std_out, std_err):
    std_out = std_out.split("\n")[-100:]
    log = {}
    len_std = len(std_out)
    for i in range(0, len_std):
        log[i] = std_out[i]

    std_err = std_err.split("\n")
    for err in std_err:
        if err != "":
            len_std += 1
            log[len_std] = "ERROR: {}".format(err)

    return log


class HelmChart:
    repos_needed = []
    docker_containers_used = {}
    max_tries = 3

    def __eq__(self, other):
        return "{}:{}".format(self.name, self.version) == "{}:{}".format(other.name, other.version)

    def __init__(self, chartfile):
        name = None
        repo = None
        version = None
        nested = False
        self.log_list = []

        if not os.path.isfile(chartfile):
            print("ERROR: Chartfile not found.")
            exit(1)

        if os.path.dirname(os.path.dirname(chartfile)).split("/")[-1] == "charts":
            nested = True

        with open(chartfile) as f:
            read_file = f.readlines()
            read_file = [x.strip() for x in read_file]

            for line in read_file:
                if "name:" in line:
                    name = line.split(": ")[1].strip()
                elif "repo:" in line:
                    repo = line.split(": ")[1].strip()
                elif "version:" in line:
                    version = line.split(": ")[1].strip()

        if repo is None:
            repo = "kaapana"

        if name is not None and version is not None and repo is not None:
            self.name = name
            self.repo = repo
            self.version = version
            self.path = chartfile
            self.chart_dir = os.path.dirname(chartfile)
            self.dev = False
            self.requirements_ready = False
            self.nested = nested
            self.requirements = []

            if "-vdev" in version:
                self.dev = True

            self.chart_id = "{}/{}:{}".format(self.repo,
                                              self.name, self.version)

            print("")
            print("Adding new chart:")
            print("name: {}".format(name))
            print("version: {}".format(version))
            print("repo: {}".format(repo))
            print("chart_id: {}".format(self.chart_id))
            print("dev: {}".format(self.dev))
            print("nested: {}".format(self.nested))
            print("file: {}".format(chartfile))
            print("")

            if self.repo not in HelmChart.repos_needed:
                HelmChart.repos_needed.append(self.repo)

            if not self.nested:
                for log_entry in self.check_requirements():
                    self.log_list.append(log_entry)
                log_entry = {
                    "suite": suite_tag,
                    "test": "{}:{}".format(self.name, self.version),
                    "step": "Extract Chart Infos",
                    "loglevel": "DEBUG",
                    "timestamp": get_timestamp(),
                    "log": "",
                    "message": "Chart added successfully.",
                    "rel_file": self.chart_dir,
                }
                self.log_list.append(log_entry)

            self.check_container_use()

        else:
            log_entry = {
                "suite": suite_tag,
                "test": "{}".format(self.name if self.name is not None else chartfile),
                "step": "Extract Chart Infos",
                "log": "",
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "message": "Could not extract all infos from chart.",
                "rel_file": chartfile,
            }
            self.log_list.append(log_entry)

            print("")
            print("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            print("")
            print("ERROR: Cound not extract all infos from chart...")
            print("name: {}".format(name))
            print("version: {}".format(version))
            print("repo: {}".format(repo))
            print("file: {}".format(chartfile))
            print("")
            print("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            print("")

    def check_requirements(self):
        print()
        print("Search for requirements...")
        log_list = []

        for requirements_file in Path(self.chart_dir).rglob('requirements.yaml'):
            with open(str(requirements_file)) as f:
                requirements_file = f.readlines()
            requirements_file = [x.strip() for x in requirements_file]
            last_req_name = ""
            last_req_version = ""
            req_repo = ""

            req_names_count = 0
            req_version_count = 0
            req_repo_count = 0

            for line in requirements_file:
                if "name:" in line:
                    req_names_count += 1
                    last_req_name = line.split(": ")[1].strip()
                if "version:" in line:
                    req_version_count += 1
                    last_req_version = line.split(": ")[1].strip()
                if "repository:" in line:
                    req_repo_count += 1
                    req_repo = line.split("/")[-1].strip()

                if req_repo != "" and last_req_name != "" and last_req_version != "":
                    req_id = "{}/{}:{}".format(req_repo,
                                               last_req_name, last_req_version)

                    if req_id not in self.requirements:
                        print("Add requirement: {}".format(req_id))
                        self.requirements.append(req_id)

                    last_req_name = ""
                    last_req_version = ""
                    req_repo = ""

            if not (req_names_count == req_repo_count == req_version_count):
                print("Something went wrong with the requirements...")
                log_entry = {
                    "suite": suite_tag,
                    "test": "{}:{}".format(self.name, self.version),
                    "step": "Requirements",
                    "loglevel": "FATAL",
                    "timestamp": get_timestamp(),
                    "log": "",
                    "message": "Something went wrong with requirements extraction.",
                    "rel_file": self.chart_dir,
                }
                log_list.append(log_entry)
            else:
                log_entry = {
                    "suite": suite_tag,
                    "test": "{}:{}".format(self.name, self.version),
                    "step": "Requirements",
                    "loglevel": "DEBUG",
                    "timestamp": get_timestamp(),
                    "log": "",
                    "message": "Requirements extracted successfully.",
                    "rel_file": self.chart_dir,
                }
                log_list.append(log_entry)

        print("Added {} requirements! done.".format(len(self.requirements)))
        print()
        return log_list

    def check_container_use(self):
        print("check_container_use: {}".format(self.chart_dir))
        glob_path = '{}/templates/*.yaml'.format(self.chart_dir)
        for yaml_file in glob.glob(glob_path, recursive=True):
            with open(yaml_file, "r") as yaml_content:
                for line in yaml_content:
                    line = line.rstrip()
                    if "dktk-jip-registry.dkfz.de" in line and "image" in line and "#" not in line:
                        docker_container = "dktk-jip-registry.dkfz.de" + \
                            line.split(
                                "dktk-jip-registry.dkfz.de")[1].replace(" ", "").replace(",", "").lower()
                        if docker_container not in HelmChart.docker_containers_used.keys():
                            HelmChart.docker_containers_used[docker_container] = yaml_file

    def dep_up(self, chart_dir=None, log_list=[]):
        if chart_dir is None:
            chart_dir = self.chart_dir
            log_list = []
        print("dep_up_chart: {}".format(chart_dir))

        dep_charts = os.path.join(chart_dir, "charts")
        if os.path.isdir(dep_charts):
            for item in os.listdir(dep_charts):
                path = os.path.join(dep_charts, item)
                if os.path.isdir(path):
                    log_list = self.dep_up(chart_dir=path, log_list=log_list)

        os.chdir(chart_dir)
        try_count = 0
        command = ["helm", "dep", "up"]

        output = run(command, stdout=PIPE, stderr=PIPE, universal_newlines=True, timeout=60)
        while output.returncode != 0 and try_count < HelmChart.max_tries:
            print("Error dep up -> try: {}".format(try_count))
            output = run(command, stdout=PIPE, stderr=PIPE, universal_newlines=True, timeout=60)
            try_count += 1
        log = make_log(std_out=output.stdout, std_err=output.stderr)



        if output.returncode != 0:
            print("Error with dep up!")
            print("Path: {}".format(chart_dir))
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm dep up",
                "log": log,
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "message": "repo update failed: {}".format(chart_dir),
                "rel_file": chart_dir,

            }

        else:
            print("dep up ok...")
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm dep up",
                "log": "",
                "loglevel": "DEBUG",
                "timestamp": get_timestamp(),
                "message": "Dependencies have been successfully updated",
                "rel_file": chart_dir,
            }

        log_list.append(log_entry)
        return log_list

    def remove_tgz_files(self):
        glob_path = '{}/charts'.format(self.chart_dir)
        for path in Path(glob_path).rglob('*.tgz'):
            print("Deleting: {}".format(path))
            os.remove(path)

        requirements_lock = '{}/requirements.lock'.format(self.chart_dir)
        if os.path.exists(requirements_lock):
            os.remove(requirements_lock)

    def lint_chart(self):
        print("lint_chart: {}/Chart.yaml".format(self.chart_dir))

        os.chdir(self.chart_dir)
        command = ["helm", "lint"]
        output = run(command, stdout=PIPE, stderr=PIPE,
                     universal_newlines=True, timeout=5)
        log = make_log(std_out=output.stdout, std_err=output.stderr)

        if output.returncode != 0:
            print("Error with lint!")
            print("Path: {}".format(self.path))
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm lint",
                "log": log,
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "message": "Helm lint failed: {}".format(self.path),
                "rel_file": self.path,
                "test_done": True,
            }
        else:
            print("Helm lint ok...")
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm lint",
                "log": "",
                "loglevel": "DEBUG",
                "timestamp": get_timestamp(),
                "message": "Helm lint was successful!",
                "rel_file": self.path,
            }

        yield log_entry

    def lint_kubeval(self):
        print("kubeval_chart: {}/Chart.yaml".format(self.chart_dir))

        os.chdir(self.chart_dir)
        command = ["helm", "kubeval", "--ignore-missing-schemas", "."]
        output = run(command, stdout=PIPE, stderr=PIPE, universal_newlines=True, timeout=10)
        log = make_log(std_out=output.stdout, std_err=output.stderr)

        if output.returncode != 0 and "A valid hostname" not in output.stderr:
            print(json.dumps(log, indent=4, sort_keys=True))
            print("Error with kubeval!")
            print("Path: {}".format(self.path))
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm kubeval",
                "log": log,
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "message": "Kubeval failed: {}".format(self.path),
                "rel_file": self.path,
                "test_done": True,
            }
        else:
            print("Kubeval ok...")
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm kubeval",
                "log": "",
                "loglevel": "DEBUG",
                "timestamp": get_timestamp(),
                "message": "Kubeval was successful!",
                "rel_file": self.path,
            }

        yield log_entry

    def push(self):
        print("Starting Helm push: {}".format(self.chart_dir))
        os.chdir(os.path.dirname(self.chart_dir))
        try_count = 0

        command = ["helm", "push", self.name, self.repo]
        output = run(command, stdout=PIPE, stderr=PIPE, universal_newlines=True, timeout=60)
        while output.returncode != 0 and try_count < HelmChart.max_tries:
            print("Error push -> try: {}".format(try_count))
            output = run(command, stdout=PIPE, stderr=PIPE, universal_newlines=True, timeout=60)
            try_count += 1
        log = make_log(std_out=output.stdout, std_err=output.stderr)

        if output.returncode != 0 or "The Kubernetes package manager" in output.stdout:
            print("Error while 'push' -> continue")
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm push",
                "log": log,
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "message": "push failed: {}".format(self.name),
                "rel_file": self.path,
                "test_done": True,
            }
            yield log_entry

        else:
            log_entry = {
                "suite": suite_tag,
                "test": "{}:{}".format(self.name, self.version),
                "step": "Helm push",
                "log": log,
                "loglevel": "DEBUG",
                "timestamp": get_timestamp(),
                "message": "Chart pushed successfully!",
                "rel_file": self.path,
                "test_done": True,
            }
            yield log_entry


def check_repos(user, pwd):
    if user is None:
        user = input("Registry user: ")

    if pwd is None:
        print("User: {}".format(user))
        pwd = getpass.getpass("password: ")

    for repo in HelmChart.repos_needed:
        print("Add repo: {}".format(repo))

        command = ["helm", "repo", "add", "--username", user, "--password", pwd, repo, "https://dktk-jip-registry.dkfz.de/chartrepo/{}".format(repo)]
        output = run(command, stdout=PIPE, stderr=PIPE,
                     universal_newlines=True, timeout=30)
        log = make_log(std_out=output.stdout, std_err=output.stderr)

        if output.returncode != 0 and '401 Unauthorized' in output.stderr:
            print("Could not add repo: {}".format(repo))
            log_entry = {
                "suite": suite_tag,
                "test": "Add repos",
                "step": repo,
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "log": log,
                "message": "Access denied! -> check credentials + repo access!",
                "rel_file": "",
            }
            yield log_entry

        elif output.returncode != 0:
            print("Could not add repo: {}".format(repo))
            log_entry = {
                "suite": suite_tag,
                "test": "Add repos",
                "step": repo,
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "log": log,
                "message": "repo add failed: {}".format(repo),
                "rel_file": "",
            }
            yield log_entry

        else:
            log_entry = {
                "suite": suite_tag,
                "test": "Add repos",
                "step": repo,
                "loglevel": "DEBUG",
                "timestamp": get_timestamp(),
                "log": "",
                "message": "Repo has been added successfully!",
                "rel_file": "",
            }
            yield log_entry
    log_entry = {
        "suite": suite_tag,
        "test": "Add repos",
        "loglevel": "DEBUG",
        "timestamp": get_timestamp(),
        "test_done": True
    }
    yield log_entry

def quick_check():
    global build_ready_list
    build_ready_list = []

    kaapana_dir = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    chartfiles = glob.glob(kaapana_dir+"/**/Chart.yaml", recursive=True)
    chartfiles = sorted(chartfiles, key=lambda p: (-p.count(os.path.sep), p))

    chartfiles_count = len(chartfiles)
    print("Found {} Charts".format(len(chartfiles)))

    charts_list = []
    for chartfile in chartfiles:
        if "node_modules" in chartfile:
            log_entry = {
                "suite": suite_tag,
                "test": chartfile.split("/")[-2],
                "step": "NODE_MODULE Check",
                "log": "",
                "loglevel": "WARN",
                "timestamp": get_timestamp(),
                "message": "Found node_module chartfile.",
                "rel_file": chartfile,
                "test_done": True,
            }
            yield log_entry
            continue

        chart_object = HelmChart(chartfile)

        if not chart_object.nested:
            for log in chart_object.log_list:
                yield log
            charts_list.append(chart_object)

    resolve_tries = 0

    print("Resolving dependencies...")
    while resolve_tries <= HelmChart.max_tries and len(charts_list) != 0:
        print("Try count: {}".format(resolve_tries))
        resolve_tries += 1

        to_do_charts = []
        for chart in charts_list:
            if "theia" in chart.chart_id:
                print("here")
            if len(chart.requirements) == 0:
                build_ready_list.append(chart)
            else:
                requirements_left = []
                for requirement in chart.requirements:
                    found = False
                    for ready_chart in build_ready_list:
                        if requirement == ready_chart.chart_id:
                            found = True
                    if not found:
                        requirements_left.append(requirement)

                chart.requirements = requirements_left

                if len(requirements_left) > 0:
                    to_do_charts.append(chart)
                else:
                    log_entry = {
                        "suite": suite_tag,
                        "test": chart.name,
                        "step": "Check Dependencies",
                        "log": "",
                        "loglevel": "DEBUG",
                        "timestamp": get_timestamp(),
                        "message": "All dependencies ok",
                        "rel_file": "",
                    }
                    build_ready_list.append(chart)
                    yield log_entry

        charts_list = to_do_charts

    if resolve_tries > HelmChart.max_tries:
        print("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        print()
        print("Could not resolve all dependencies...")
        print("The following charts had problems: ")
        for chart in reversed(charts_list):
            miss_deps = []
            print()
            print("Chart: {}".format(chart.name))
            print()
            print("Requirements left: ")
            for req in chart.requirements:
                print(req)
                miss_deps.append(req)
            print()

            log_entry = {
                "suite": suite_tag,
                "test": chart.name,
                "step": "Check Dependencies",
                "log": {"Missing dependency": miss_deps},
                "loglevel": "ERROR",
                "timestamp": get_timestamp(),
                "message": "Could not resolve all dependencies",
                "rel_file": "",
            }
            yield log_entry
            build_ready_list.append(chart)

    else:
        print("All dependencies ok...")
        log_entry = {
            "suite": suite_tag,
            "test": chart.name,
            "step": "Check Dependencies",
            "log": "",
            "loglevel": "DEBUG",
            "timestamp": get_timestamp(),
            "message": "Successful",
            "rel_file": "",
        }
        yield log_entry

    yield build_ready_list, HelmChart.docker_containers_used


############################################################
######################   START   ###########################
############################################################

def start(p_user=None, p_pwd=None):
    global build_ready_list
    user = p_user
    pwd = p_pwd

    check_helm_installed()

    if build_ready_list is None or len(build_ready_list) == 0:
        for log in quick_check():
            if type(log) == dict:
                if log['loglevel'].lower() == "error" or log['loglevel'].lower() == "fatal":
                    print(
                        "+++++++++++++++++++++++++++++++++++++++ ERROR! +++++++++++++++++++++++++++++++++++++++")
                    print(
                        "+++++++++++++++++++++++++++++++++ QUICK CHECK FAILED! ++++++++++++++++++++++++++++++++")
                    print("")
                    print(json.dumps(log, sort_keys=True, indent=4))
                    # exit(1)
            else:
                build_ready_list, docker_containers_used = log

    print()
    print("Adding needed repositories...")
    for log in check_repos(user=user, pwd=pwd):
        if log['loglevel'].lower() == "error" or log['loglevel'].lower() == "fatal":
            print(
                "+++++++++++++++++++++++++++++++++++++++ ERROR! +++++++++++++++++++++++++++++++++++++++")
            print(
                "+++++++++++++++++++++++++++++++++++ REPO ADD FAILED! +++++++++++++++++++++++++++++++++")
            print("")
            print(json.dumps(log, sort_keys=True, indent=4))
        yield log

    print()
    print("Start build and push process...")
    for chart in build_ready_list:
        print("Build and push chart: {}".format(chart.chart_id))
        skip_chart = False
        chart.remove_tgz_files()

        for log_entry in chart.dep_up():
            if log_entry['loglevel'].lower() == "error" or log_entry['loglevel'].lower() == "fatal":
                skip_chart = True
            yield log_entry

        if skip_chart:
            continue

        for log_entry in chart.lint_chart():
            if log_entry['loglevel'].lower() == "error" or log_entry['loglevel'].lower() == "fatal":
                # skip_chart = True
                print("Lint problems -> but not skipping!")
            yield log_entry

        if skip_chart:
            continue

        for log_entry in chart.lint_kubeval():
            # if log_entry['loglevel'].lower() == "error" or log_entry['loglevel'].lower() == "fatal":
            #     skip_chart = True
            yield log_entry

        if skip_chart:
            continue

        for log_entry in chart.push():
            yield log_entry

    print("FINISHED")


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("-u", "--username", dest="user",
                        default=None, help="Registry username")
    parser.add_argument("-p", "--password", dest="pwd",
                        default=None, help="Registry password")

    args = parser.parse_args()
    user = args.user
    pwd = args.pwd

    for log in start(p_user=user, p_pwd=pwd):
        print(json.dumps(log, sort_keys=True, indent=4))
        if log['loglevel'].lower() == "error":
            print("ERROR! +++++++++++++++++++++++++++++++++++++++++++++++++")
            exit(1)
