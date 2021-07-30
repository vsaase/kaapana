import error_handler
import ci_playbooks
import platform_ui_tests
import json
from time import time
from multiprocessing import Process
import traceback
from argparse import ArgumentParser
from reportportal_client import ReportPortalService
# from reportportal_client import ReportPortalServiceAsync
import getpass
import subprocess
import os
import signal
import sys
from git import Repo
import datetime
import signal
import importlib

kaapana_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
exceptions_file = os.path.join(kaapana_dir, "CI", "scripts", "ci_exceptions.json")
ansible_playbook_dir = os.path.join(kaapana_dir, "CI", "ansible_playbooks")
build_charts_helper_file = os.path.join(kaapana_dir, "build_scripts", "build_helper", "charts_build_and_push_all.py")
build_containers_helper_file = os.path.join(kaapana_dir, "build_scripts", "build_helper", "containers_build_and_push_all.py")

# sys.path.insert(1, '/home/ubuntu/kaapana/build_scripts/build_helper')
# from charts_build_and_push_all import HelmChart, init_helm_charts, helm_registry_login
# from containers_build_and_push_all import start_container_build, container_registry_login

# Some parameters required for build process
os.environ["HELM_EXPERIMENTAL_OCI"] = "1"
log_list = {
    "CONTAINERS": [],
    "CHARTS": [],
    "OTHER": []
}
# TODO: maybe get rid of the following log level parameters
supported_log_levels = ["DEBUG", "WARN", "ERROR"]
log_level = "WARN"

## To import module from another directory
def module_from_file(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

charts_build_and_push_all = module_from_file("charts_build_and_push_all", build_charts_helper_file)
containers_build_and_push_all = module_from_file("containers_build_and_push_all", build_containers_helper_file)

# Item type one of 'SUITE', 'STORY', 'TEST', 'SCENARIO', 'STEP', 'BEFORE_CLASS', 'BEFORE_GROUPS','BEFORE_METHOD', 'BEFORE_SUITE', 'BEFORE_TEST', 'AFTER_CLASS', 'AFTER_GROUPS', 'AFTER_METHOD', 'AFTER_SUITE', 'AFTER_TEST'
# status, one of "PASSED", "FAILED", "STOPPED", "SKIPPED", "INTERRUPTED", "CANCELLED". Default: "PASSED".
suites = {}
rp_service = None
lock_file = None
suite_done = None
mail_max = 10
mail_counter = 0

username = None
password = None
os_image= "ubuntu"
os_project_name = "E230"
os_project_id = "1396d67192c24eb7ab606cfae1151208"
start_parameters = ""

volume_size = "90"
instance_flavor = "dkfz-8.16"
ssh_key = "kaapana"
registry_user = None
registry_pwd = None
registry_url = None
http_proxy=""

ci_servers = {}

class SkipException(Exception):
    """Exception raised for errors within the build-process.

    Attributes:
        reason  -- reason why the container was skipped for the build process
    """

    def __init__(self, reason, log=None):
        self.reason = reason
        if "container" in log:
            del log['container']
        self.log = log
        super().__init__(self.reason)

    def __str__(self):
        if self.log is not None:
            return self.reason + "\n" + json.dumps(self.log, indent=4, sort_keys=True)
        else:
            return self.reason

with open(exceptions_file, 'r') as f:
    ci_exceptions = json.load(f)


def get_timestamp():
    return str(int(time() * 1000))


def terminate_session(result_code, ci_status="PASSED"):
    # status: "PASSED", "FAILED", "STOPPED", "SKIPPED", "INTERRUPTED", "CANCELLED".
    # status can be (PASSED, FAILED, STOPPED, SKIPPED, RESETED, CANCELLED)
    if disable_report:
        return
    global lock_file, rp_service, suites

    for suite_name, suite_dict in suites.items():
        if suite_dict["running"] and suite_name != "launch":
            print("stopping suite: {}".format(suite_name))
            suite_dict["status"] = "SKIPPED"
            for test_name, test_dict in suite_dict["tests"].items():
                if test_dict["running"]:
                    print("stopping test: {}".format(test_name))
                    test_dict["status"] = "SKIPPED"
                    test_dict["issue_type"] = "TI001"
                    try:
                        rp_service.finish_test_item(item_id=test_dict["id"], end_time=get_timestamp(), status=test_dict["status"],  issue={"issue_type": test_dict["issue_type"]})
                        test_dict["running"] = False
                    except Exception as e:
                        print("RP: {}".format(e.args[0]))
                        pass
            try:
                rp_service.finish_test_item(item_id=suite_dict["id"], end_time=get_timestamp(), status=suite_dict["status"])
                suite_dict["running"] = False
            except Exception as e:
                print("RP: {}".format(e.args[0]))
                pass
    try:
        rp_service.finish_launch(end_time=get_timestamp(), status=ci_status)
    except Exception as e:
        pass

    rp_service.terminate()

    try:
        os.remove(lock_file)
    except Exception as e:
        pass

    exit(result_code)


def handle_logs(log_dict):
    if disable_report:
        return
    global rp_service,  mail_notification, mail_counter, mail_max, ci_exceptions, suites
    suite = log_dict["suite"] if log_dict["suite"] is not None else "launch"
    reason = log_dict["message"] if "message" in log_dict else ""
    log = log_dict["log"] if "log" in log_dict else ""
    loglevel = log_dict["loglevel"].lower(
    ) if "loglevel" in log_dict else "info"
    rel_file = log_dict["rel_file"] if "rel_file" in log_dict else ""
    test = log_dict["test"] if "test" in log_dict else None
    step = log_dict["step"] if "step" in log_dict else None
    suite_done = log_dict["suite_done"] if "suite_done" in log_dict else False
    test_done = log_dict["test_done"] if "test_done" in log_dict else False
    nested_suite = log_dict["nested_suite"] if "nested_suite" in log_dict else None
    timestamp = log_dict["timestamp"] if "timestamp" in log_dict else get_timestamp(
    )

    if suite is not None and suite.count(".") == 3:
        for key, val in ci_servers.items():
            if val["ip"] == suite:
                suite = "{}: {}".format(key, suite)

    if suite is not None and not suite_done and ((suite not in suites or not suites[suite]["running"]) or nested_suite is not None):
        if suite in suites and not suites[suite]["running"]:
            # print("Removed old suite and add new one!")
            del suites[suite]
        if nested_suite is not None:
            print("Starting nested suite!")
            print(suite)
            item_id = suites[suite]["id"]
            suite = nested_suite
            suite_id = rp_service.start_test_item(name=suite, parent_item_id=item_id, description="",
                                                  start_time=timestamp, item_type="SUITE", parameters={"branch": branch_name})
        else:
            # print("Start new suite: {}".format(suite))
            suite_id = rp_service.start_test_item(
                name=suite,  description="", start_time=timestamp, item_type="SUITE", parameters={"branch": branch_name})

        suites[suite] = {
            "id": suite_id,
            "name": suite,
            "status": "PASSED",
            "running": True,
            "tests": {},
        }

    suite_dict = suites[suite]
    item_id = suite_dict["id"]

    if test is not None and not test_done and (test not in suite_dict["tests"] or not suite_dict["tests"][test]["running"]):
        # print("Start new test {}: {}".format(suite_dict["name"], test))
        test_id = rp_service.start_test_item(name=test, parent_item_id=item_id, description="",
                                             start_time=timestamp, item_type="TEST", parameters={"branch": branch_name})
        test_dict = {
            "id": test_id,
            "name": test,
            "status": "PASSED",
            "issue_type": "NOT_ISSUE",
            "running": True
        }
        suite_dict["tests"][test] = test_dict

    test_dict = suite_dict["tests"][test] if test is not None else None
    if test_dict is not None:
        item_id = test_dict["id"]

    if loglevel is not None and loglevel == "error" and mail_notification and mail_counter < mail_max and rel_file != "" and rel_file is not None:
        print("################################################ -> SENDING EMAIL No {}".format(mail_counter))
        error_handler.notify_maintainers(logs_dict=log_dict)
        mail_counter += mail_counter

    if suite_dict is not None and loglevel == "error":
        suite_dict["status"] = "FAILED"

    if test_dict is not None and loglevel == "error":
        test_dict["status"] = "FAILED"
        test_dict["issue_type"] = "PB001"

    elif test_dict is not None and loglevel == "warn" and test_dict["status"].lower() == "passed":
        test_dict["status"] = "SKIPPED"
        test_dict["issue_type"] = "TI001"

    elif test_dict is not None and loglevel == "ab":
        test_dict["status"] = "SKIPPED"
        test_dict["issue_type"] = "AB001"
        loglevel = "warn"

    if test_dict is not None and test in ci_exceptions["test_exceptions"]:
        test_dict["status"] = "SKIPPED"
        test_dict["issue_type"] = "AB001"

    if step is not None:
        try:
            message = "**{}:** {}\n{}".format(step, reason, rel_file)
            if log == "":
                log_id = rp_service.log(time=timestamp, message="**{}:** {}\n{}".format(
                    step, reason, rel_file), level=loglevel, item_id=item_id)
            else:
                log_id = rp_service.log(time=timestamp, message="**{}:** {}\n{}".format(step, reason, rel_file), level=loglevel, item_id=item_id,
                                        attachment={
                    "name": "{}_logs.txt".format(step),
                    "data": json.dumps(log, sort_keys=True, indent=4),
                    "mime": "application/json"
                })
        except Exception as e:
            print("RP Exception occurred: ")
            print(e)
            if "success" in e.args[0]:
                print("RP: {}".format(e.args[0]))
            else:
                print("Error RP: {}".format(e.args[0]))
                raise Exception("RP error!")

    if test_done == True:
        # print("stopping test: {}".format(test))
        try:
            test_dict = suites[suite]["tests"][test]
            stop_id = rp_service.finish_test_item(item_id=test_dict["id"], end_time=timestamp, status=test_dict["status"],  issue={
                                                  "issue_type": test_dict["issue_type"]})
            test_dict["running"] = False
        except Exception as e:
            print("RP Exception occurred: ")
            print(e)
            print("RP: {}".format(e.args[0]))
            pass

    elif suite_done == True:
        # print("stopping suite: {}".format(suite))
        try:
            suite_dict = suites[suite]
            for test_name, test_dict in suite_dict["tests"].items():
                if test_dict["running"]:
                    # print("stopping test: {}".format(test_name))
                    rp_service.finish_test_item(item_id=test_dict["id"], end_time=timestamp, status=test_dict["status"],  issue={
                                                "issue_type": test_dict["issue_type"]})
                    test_dict["running"] = False

            rp_service.finish_test_item(
                item_id=suite_dict["id"], end_time=timestamp, status=suite_dict["status"])
            suite_dict["running"] = False
        except Exception as e:
            print("RP Exception occurred: ")
            print(e)
            print("RP: {}".format(e.args[0]))
            pass


def print_log_entry(log_entry, kind="OTHER"):
    log_entry_loglevel = log_entry['loglevel'].upper()
    if supported_log_levels.index(log_entry_loglevel) >= log_level:
        print("-----------------------------------------------------------")
        print("Log: {}".format(log_entry["test"]))
        print("Step: {}".format(log_entry["step"] if "step" in log_entry else "N/A"))
        print("Message: {}".format(log_entry["message"] if "message" in log_entry else "N/A"))
        print("-----------------------------------------------------------")

    if "container" in log_entry:
        del log_entry['container']
    log_list[kind].append([log_entry_loglevel, json.dumps(log_entry, indent=4, sort_keys=True)])


def check_containers():
    log = {
        "suite": containers_build_and_push_all.suite_tag,
        "step": "started"
    }
    handle_logs(log)

    for container_log in build_and_push_containers():
        if container_log["test"].lower() != "return":
            handle_logs(container_log)

    log = {
        "suite": containers_build_and_push_all.suite_tag,
        "suite_done": True,
    }
    handle_logs(log)


def check_charts(container_tag_list=[]):
    log = {
        "suite": charts_build_and_push_all.suite_tag,
        "step": "started"
    }
    handle_logs(log)

    for chart_log in build_and_push_charts():
        if chart_log["test"].lower() != "return":
            handle_logs(chart_log)

    log = {
        "suite": charts_build_and_push_all.suite_tag,
        "suite_done": True,
    }
    handle_logs(log)


def build_and_push_charts():

    charts_build_and_push_all.helm_registry_login(container_registry=registry_url, username=registry_user, password=registry_pwd)

    print("-----------------------------------------------------------")
    print("------------------------- CHARTS --------------------------")
    print("-----------------------------------------------------------")

    print("Init HelmCharts...")
    charts_build_and_push_all.init_helm_charts(kaapana_dir=kaapana_dir, chart_registry=registry_url)

    print("Start quick_check...")
    # for log_entry in HelmChart.quick_check(push_charts_to_docker):
    for log_entry in charts_build_and_push_all.HelmChart.quick_check():
        if isinstance(log_entry, dict):
            print_log_entry(log_entry, kind="CHARTS")
        else:
            all_charts = log_entry

    print("Creating build order ...")

    tries = 0
    max_tries = 5
    build_ready_list = []
    not_ready_list = all_charts.copy()
    while len(not_ready_list) > 0 and tries < max_tries:
        tries += 1
        all_ready = True
        not_ready_list_tmp = []
        for chart in not_ready_list:
            chart.dependencies_ready = True
            for dependency in chart.dependencies:
                ready_charts = [ready_chart for ready_chart in build_ready_list if ready_chart.name == dependency["name"] and ready_chart.version == dependency["version"]]
                if len(ready_charts) == 0:
                    chart.dependencies_ready = False
                    break
            if chart.dependencies_ready:
                build_ready_list.append(chart)
            else:
                not_ready_list_tmp.append(chart)

        not_ready_list = not_ready_list_tmp

    if tries >= max_tries:
        print("#########################################################################")
        print("")
        print("                    Issue with dependencies!")
        print("")
        print("#########################################################################")
        print("")
        for chart in not_ready_list:
            print(f"Missing dependencies for chat: {chart.name}")
            print("")
        print("")
        exit(1)

    print("Start build- and push-process ...")
    i = 0
    for chart in build_ready_list:
        i += 1
        try:
            print()
            print("chart: {}".format(chart.chart_id))
            print("{}/{}".format(i, len(build_ready_list)))
            print()
            chart.remove_tgz_files()
            print("dep up ...")
            for log_entry in chart.dep_up():
                yield log_entry
                # print_log_entry(log_entry, kind="CHARTS")
                if log_entry['loglevel'].upper() == "ERROR":
                    raise SkipException("SKIP {}: dep_up() error!".format(log_entry['test']), log=log_entry)
                

            print("linting ...")
            for log_entry in chart.lint_chart():
                yield log_entry
                # print_log_entry(log_entry, kind="CHARTS")
                if log_entry['loglevel'].upper() == "ERROR":
                    raise SkipException("SKIP {}: lint_chart() error!".format(log_entry['test']), log=log_entry)
                
                
            print("kubeval ...")
            for log_entry in chart.lint_kubeval():
                yield log_entry
                # print_log_entry(log_entry, kind="CHARTS")
                if log_entry['loglevel'].upper() == "ERROR":
                    raise SkipException("SKIP {}: lint_kubeval() error!".format(log_entry['test']), log=log_entry)
                    

            if "platforms" in chart.chart_dir and not chart.local_only:
                print("saving chart ...")
                # for log_entry in chart.chart_save():
                #     yield log_entry
                #     # print_log_entry(log_entry, kind="CHARTS")
                #     if log_entry['loglevel'].upper() == "ERROR":
                #         raise SkipException("SKIP {}: chart_save() error!".format(log_entry['test']), log=log_entry)
                    

                # print("pushing chart ...")
                # for log_entry in chart.chart_push():
                #     yield log_entry
                #     # print_log_entry(log_entry, kind="CHARTS")
                #     if log_entry['loglevel'].upper() == "ERROR":
                #         raise SkipException("SKIP {}: chart_push() error!".format(log_entry['test']), log=log_entry)
                        

            print()
            print()
        except SkipException as error:
            print("SkipException: {}".format(str(error)))


def build_and_push_containers():

    containers_build_and_push_all.container_registry_login(container_registry=registry_url, username=registry_user, password=registry_pwd)

    print("-----------------------------------------------------------")
    print("------------------------ CONTAINER ------------------------")
    print("-----------------------------------------------------------")
    config_list = (kaapana_dir, http_proxy, registry_url)
    docker_containers_list, logs = containers_build_and_push_all.start_container_build(config=config_list)

    for log in logs:
        if supported_log_levels.index(log['loglevel'].upper()) >= log_level:
            # print_log_entry(log, kind="CONTAINERS")
            handle_logs(log)
        if log['loglevel'].upper() == "ERROR":
            exit(1)

    i = 0
    for docker_container in docker_containers_list:
        i += 1
        print()
        print("Container: {}".format(docker_container.tag.replace(docker_container.container_registry, "")[1:]))
        print("{}/{}".format(i, len(docker_containers_list)))
        print()
        try:
            if docker_container.ci_ignore:
                print('SKIP {}: CI_IGNORE == True!'.format(docker_container.tag.replace(docker_container.container_registry, "")[1:]))
                continue
            for log in docker_container.check_prebuild():
                # print_log_entry(log, kind="CONTAINERS")
                yield log
                if log['loglevel'].upper() == "ERROR":
                    raise SkipException('SKIP {}: check_prebuild() failed!'.format(log['test']), log=log)

            for log in docker_container.build():
                # print_log_entry(log, kind="CONTAINERS")
                yield log
                if log['loglevel'].upper() == "ERROR":
                    raise SkipException('SKIP {}: build() failed!'.format(log['test']), log=log)

            # for log in docker_container.push():
            #     # print_log_entry(log, kind="CONTAINERS")
            #     yield log
            #     if log['loglevel'].upper() == "ERROR":
            #         raise SkipException('SKIP {}: push() failed!'.format(log['test']), log=log)

        except SkipException as error:
            print("SkipException: {}".format(str(error)))
            continue


def start_os_instance(instance_name, os_image, suite_name="Start Test Server Instance"):
    return_value, logs = ci_playbooks.start_os_instance(username=username,
                                                        password=password,
                                                        instance_name=instance_name,
                                                        project_name=os_project_name,
                                                        project_id=os_project_id,
                                                        os_image=os_image,
                                                        volume_size=volume_size,
                                                        instance_flavor=instance_flavor,
                                                        ssh_key=ssh_key,
                                                        suite_name=suite_name)
    for log in logs:
        handle_logs(log)

    return return_value


def install_dependencies(target_hosts, os_image="ubuntu", suite_name="Install Server Dependencies"):
    print("target_hosts: {}".format(target_hosts))
    print("suite_name: {}".format(suite_name))
    return_value, logs = ci_playbooks.start_install_server_dependencies(target_hosts=target_hosts, remote_username=os_image, suite_name=suite_name)
    for log in logs:
        handle_logs(log)

    return return_value


def deploy_platform(target_hosts, platform_name, os_image="ubuntu", suite_name="Deploy Platform"):
    return_value, logs = ci_playbooks.deploy_platform(target_hosts=target_hosts, remote_username=os_image, registry_user=registry_user, registry_pwd=registry_pwd, registry_url=registry_url, platform_name=platform_name)
    for log in logs:
        handle_logs(log)

    return return_value


def start_ui_tests(target_hosts, platform_name, suite_name="UI Tests"):
    for log in platform_ui_tests.start(platform_urls=target_hosts, suite_name=suite_name, test_name="{0: <14}: UI TESTS".format(platform_name)):
        handle_logs(log)

    return True


def test_platform_version(target_hosts, platform_name):
    result = deploy_platform(target_hosts=target_hosts, platform_name=platform_name)
    result = start_ui_tests(target_hosts=target_hosts, platform_name=platform_name) if result != "FAILED" else "FAILED"
    # TODO: The following 2 methods need to be uncommented when CI code is ready
    # result = remove_platform(target_hosts=target_hosts, platform_name=platform_name) 
    # result = purge_filesystem(target_hosts=target_hosts, platform_name=platform_name) if result != "FAILED" else "FAILED"

    return result


def remove_platform(target_hosts, platform_name, suite_name="Remove Platform"):
    return_value, logs = ci_playbooks.delete_platform_deployment(target_hosts=target_hosts, suite_name=suite_name, platform_name=platform_name)
    for log in logs:
        handle_logs(log)

    return return_value


def purge_filesystem(target_hosts, platform_name, suite_name="Purge Filesystem"):
    return_value, logs = ci_playbooks.purge_filesystem(
        target_hosts=target_hosts, suite_name=suite_name, platform_name=platform_name)
    for log in logs:
        handle_logs(log)

    return return_value


def delete_os_instance(instance_name, suite_name="Test Server Instance",):
    return_value, logs = ci_playbooks.delete_os_instance(
        username=username, password=password, instance_name=instance_name, suite_name=suite_name, os_project_name=os_project_name, os_project_id=os_project_id)
    for log in logs:
        handle_logs(log)

    return return_value


def delete_ci_instances(suite_name="Delete CI Instances"):
    for key, val in ci_servers.items():
        delete_os_instance(
            instance_name=val["instance_name"], suite_name=suite_name)


def startup_sequence(os_image, suite_name):

    recreated = delete_os_instance(
        instance_name=instance_name,
        suite_name=suite_name
    ) if delete_instances else "SKIPPED"

    server_ip = start_os_instance(
        instance_name=instance_name,
        os_image=os_image,
        suite_name=suite_name
    )
    if server_ip != "FAILED":
        ci_servers[os_image] = {
            "instance_name": instance_name,
            "os_image": os_image,
            "recreated": True if recreated != "SKIPPED" else False,
            "ip": server_ip
        }
    print(ci_servers)


def launch():
    global lock_file, rp_service, branch_name, suites, username, password, registry_user, registry_pwd, log_level

    username = os.environ.get('CI_USERNAME', username)
    password = os.environ.get('CI_PASSWORD', password)
    registry_user = os.environ.get('REGISTRY_USER', registry_user)
    registry_pwd = os.environ.get('REGISTRY_TOKEN', registry_pwd)

    if username is None:
        print("OpenStack credentials not found.")
        username = input("OpenStack username: ")

    if password is None:
        print("Openstack User: {}".format(username))
        password = getpass.getpass("Openstack password: ")

    if registry_user is None:
        print("Registry credentials not found.")
        username = input("Registry user/token name: ")
    
    if registry_pwd is None:
        print("Registry User: {}".format(registry_user))
        password = getpass.getpass("Registry password/token: ")

    if username is None or username == "" or password is None or password == "" or registry_user is None or registry_user == "" or registry_pwd is None or registry_pwd == "":
        print("OpenStack/Regsitry credentials not provided... Exiting!")
        exit(1)

    lock_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "ci_running.txt")
    if os.path.isfile(lock_file):
        print("CI pipeline already running!")
        print("The lock_file is present: {}".format(lock_file))
        exit(1)
    else:
        with open(lock_file, 'w') as the_file:
            the_file.write('{}'.format(os.getpid()))

    # rp_endpoint = "http://10.128.130.67:80"
    # token = "c196043d-1dd7-47d3-b4ff-ad83380e308c"
    rp_endpoint = "http://10.128.130.238:80"
    token = "bfeece88-8239-454b-a8ee-cea5fe62e7a6"
    project = "kaapana"

    launch_doc = """
    Branch: {}
    Parameters:
    {}
    """.format(branch_name,start_parameters)

    try:
        # rp_service = ReportPortalServiceAsync(endpoint=rp_endpoint, project=project, token=token, error_handler=my_error_handler) if not disable_report else None
        rp_service = ReportPortalService(endpoint=rp_endpoint, project=project, token=token) if not disable_report else None
        launch_id = rp_service.start_launch(name=launch_name, start_time=get_timestamp(), description=launch_doc) if not disable_report else None
        suites["launch"] = {
            "id": launch_id,
            "status": "PASSED",
            "running": True,
            "tests": {},
        }
    except Exception as e:
        os.remove(lock_file)
        print(e)
        print("Report portal service init error")
        exit(1)

    try:
        running_processes = []
        if not dpl_only:
            
            if log_level not in supported_log_levels:
                print("Log level {} not supported.")
                print("Please use 'DEBUG','WARN' or 'ERROR' for log_level in build-configuration.json")
                exit(1)

            log_level = supported_log_levels.index(log_level)

            if not container_only:
                check_charts()
                pass

            if not charts_only:
                check_containers()

            if charts_only or container_only:
                print("Container only: {}".format(container_only))
                print("Charts only: {}".format(charts_only))
                print("DONE.")
                exit(0)

        running_processes = []
        # os.chdir(ansible_playbook_dir)
        if not build_only:
            suite_name = "Startup Sequence"
            log = {
                "suite": suite_name,
                "step": "started"
            }
            handle_logs(log)

            if docs_test:
                startup_sequence("centos7")

            # startup_sequence("centos8")
            startup_sequence("ubuntu", suite_name)

            log = {
                "suite": suite_name,
                "suite_done": True,
            }
            handle_logs(log)

            # running_processes = []
            # if "centos7" in ci_servers and docs_test:
            #     suite_name = ci_servers["centos7"]["ip"]
            #     log = {
            #         "suite": suite_name,
            #         "step": "started"
            #     }
            #     handle_logs(log)

            #     result = install_dependencies(
            #         target_hosts=[ci_servers["centos7"]["ip"]],
            #         docs_test=True,
            #         suite_name=suite_name
            #     )

            #     platform_name = "JIP Release Docs Test"

            #     result = deploy_platform(
            #         target_hosts=[ci_servers["centos7"]["ip"]],
            #         platform_name=platform_name,
            #         docs_test=True,
            #         config_file="jip_release.yaml"
            #     ) if "centos7" in ci_servers else "FAILED"

            #     result = start_ui_tests(
            #         target_hosts=[ci_servers["centos7"]["ip"]],
            #         suite_name=suite_name,
            #         platform_name=platform_name
            #     ) if result != "FAILED" else "FAILED"

            #     result = purge_filesystem(
            #         target_hosts=[ci_servers["centos7"]["ip"]],
            #         config_file="jip_release.yaml",
            #         platform_name=platform_name,
            #         suite_name=suite_name
            #     ) if result != "FAILED" else "FAILED"

            #     log = {
            #         "suite": ci_servers["centos7"]["ip"],
            #         "suite_done": True
            #     }
            #     handle_logs(log)

            host_ips = []
            for key, val in ci_servers.items():
                if key != "centos7":
                    host_ips.append(val["ip"])
                    suite_name = val["ip"]
                    log = {
                        "suite": suite_name,
                        "step": "started"
                    }
                    handle_logs(log)

            if len(host_ips) > 0:
                result = install_dependencies(target_hosts=host_ips)
            else:
                print("No HOSTS found...")
                result = "FAILED"

            if result == "FAILED":
                print("Error installing install_dependencies...")
                terminate_session(1,ci_status="FAILED")
                exit(1)

            result = test_platform_version(
                target_hosts=host_ips,
                platform_name="Kaapana"
            )

            if all_platforms:
                result = test_platform_version(
                    target_hosts=host_ips,
                    config_file="kaapana_platform.yaml",
                    platform_name="kaapana Platform"
                )

            for ip in host_ips:
                log = {
                    "suite": ip,
                    "suite_done": True
                }
                handle_logs(log)

            print("Platform deloyment tests done.")
        else:
            print("BUILD ONLY -> Skipping deployment tests....")
            print("DONE")
    except Exception as e:
        print("Error in main routine!")
        print(traceback.format_exc())
    finally:
        print("Terminating...")
        # delete_ci_instances()
        terminate_session(0)


def handle_signal(signum, frame):
    log = {
        "suite": "CI run terminated by external signal",
        "test": "terminated",
        "loglevel": "WARN",
        "message": "The CI run was terminated by SIGTERM",
    }
    handle_logs(log)
    log = {
        "suite": "CI run terminated by external signal",
        "suite_done": True
    }
    handle_logs(log)
    terminate_session(0,ci_status="CANCELLED")


signal.signal(signal.SIGTERM, handle_signal)

if __name__ == '__main__':

    for para in sys.argv[1:]:
        start_parameters += para
        if "--branch" != para:
            start_parameters += "\n"
        else:
            start_parameters += " "

    if start_parameters == "":
        start_parameters = "None"

    parser = ArgumentParser()
    parser.add_argument("-in", "--inst-name", dest="instance_name", default="kaapana-ci-nightly-depl-test", help="Name for the CI deployment instance")
    parser.add_argument("-ln", "--launch-name", dest="launch_name", default="Kaapana CI Nightly Run", help="Name for the lauch on ReportPortal")
    parser.add_argument("-b", "--branch", dest="branch", default=None, help="Branch to run the CI on. !!CAUTION: will reset the git repo to last commit!")
    parser.add_argument("-dsm", "--disable-safe-mode", dest="disable_safe_mode", default=False, action='store_true',help="Disable safe-mode")
    parser.add_argument("-u", "--username", dest="username", default="kaapana-ci", help="Openstack Username")
    parser.add_argument("-p", "--password", dest="password", default=None, required=False, help="Openstack Password")
    parser.add_argument("-urg", "--registry-username", dest="registry_user", default=None, help="Registry Username")
    parser.add_argument("-prg", "--registry-password", dest="registry_pwd", default=None, help="Registry Password")
    parser.add_argument("-rurl", "--registry-url", dest="registry_url", default=None, help="Registry Link")
    parser.add_argument("-di", "--delete-instances", dest="delete_instances", default=False, action='store_true', help="Should a new OS CI instance be created for the tests?")
    parser.add_argument("-en", "--email-notifications", dest="mail_notify", default=False, action='store_true', help="Enable e-mail notifications for errors")
    parser.add_argument("-bo", "--build-only", dest="build_only", default=False, action='store_true', help="No platform deployment and UI tests")
    parser.add_argument("-cho", "--charts-only", dest="charts_only", default=False, action='store_true', help="Just build all helm charts")
    parser.add_argument("-co", "--container-only", dest="container_only", default=False, action='store_true', help="Just build all containers charts")
    parser.add_argument("-dr", "--disable-report", dest="disable_report", default=False, action='store_true', help="Disable report to ReportPortal")
    parser.add_argument("-depo", "--deployment-only", dest="dpl_only", default=False, action='store_true', help="Only deployment tests")
    parser.add_argument("-allp", "--all-platforms", dest="all_platforms", default=False, action='store_true', help="Test all platforms")
    parser.add_argument("-dt", "--docs-test", dest="docs_test", default=False, action='store_true', help="Test of the online documentation scripts?")

    args = parser.parse_args()
    branch = args.branch 
    disable_safe_mode = args.disable_safe_mode
    delete_instances = args.delete_instances
    username = args.username if args.username is not None else username
    password = args.password if args.password is not None else password
    registry_user = args.registry_user if args.registry_user is not None else registry_user 
    registry_pwd = args.registry_pwd if args.registry_pwd is not None else registry_pwd
    registry_url = args.registry_url if args.registry_url is not None else registry_url
    launch_name = args.launch_name
    instance_name = args.instance_name
    mail_notification = args.mail_notify
    docs_test = args.docs_test
    build_only = args.build_only
    charts_only = args.charts_only
    container_only = args.container_only
    dpl_only = args.dpl_only
    disable_report = args.disable_report
    all_platforms = args.all_platforms
    os_project_name = os_project_name
    os_project_id = os_project_id
    start_parameters = start_parameters
    volume_size = volume_size
    instance_flavor = instance_flavor
    ssh_key = ssh_key
    log_level = log_level

    repo = Repo(kaapana_dir)

    print("++++++++++++++++++++++++++++++++++++++++++++++++++")
    print()
    print("Starting CI system:")
    print(datetime.datetime.now())
    print()
    print("++++++++++++++++++++++++++++++++++++++++++++++++++")

    if branch is not None:
        print("Switching to git branch: {}".format(branch))
        if not disable_safe_mode:
            reply = str(input("This will reset the repo to the last commit of {} (y/n): ".format(branch))).lower().strip()
            if reply[0] == 'y':
                print("continuing...")
            else:
                print("goodbye")
                exit(0)

        repo.git.reset('--hard')
        repo.git.clean('-xdf')
        repo.git.checkout(branch)
        repo.remote().pull(branch)

    branch_name = repo.active_branch.name
    
    # # TODO: following is just temp, needs to be removed
    lock_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "ci_running.txt")
    if os.path.isfile(lock_file):
        print("Lock file present! Now deleting it before proceeding...")
        os.remove(lock_file)

    launch()
