from quick_check import complete_quick_check
import error_handler
import ci_playbooks
import charts_build_and_push_all
import containers_build_and_push_all
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
import sys

# Item type one of 'SUITE', 'STORY', 'TEST', 'SCENARIO', 'STEP', 'BEFORE_CLASS', 'BEFORE_GROUPS','BEFORE_METHOD', 'BEFORE_SUITE', 'BEFORE_TEST', 'AFTER_CLASS', 'AFTER_GROUPS', 'AFTER_METHOD', 'AFTER_SUITE', 'AFTER_TEST'
# status, one of "PASSED", "FAILED", "STOPPED", "SKIPPED", "INTERRUPTED", "CANCELLED". Default: "PASSED".
suites = {}
rp_service = None
lock_file = None
suite_done = None
mail_notification = False
mail_max = 10
mail_counter = 0

username = None
password = None
os_image= "ubuntu"
os_project_name = "E230-Kaapana-CI"
os_project_id = "2df9e30325c849dbadcc07d7ffd4b0d6"
start_parameters = ""

volume_size = "90"
instance_flavor = "dkfz-8.16"
ssh_key = "kaapana"
instance_name = None
launch_name = "Kaapana CI deployment test"
gitlab_username = None
gitlab_password = None
gitlab_registry = None

ci_servers = {}

kaapana_dir=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
exceptions_file = os.path.join(kaapana_dir, "CI", "scripts", "ci_exceptions.json")
ansible_playbook_dir = os.path.join(kaapana_dir, "CI", "ansible_playbooks")

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


def make_quick_check():
    log = {
        "suite": "Quick Check",
        "step": "started"
    }
    handle_logs(log)

    for log in complete_quick_check():
        handle_logs(log)

    log = {
        "suite": "Quick Check",
        "suite_done": True,
    }
    handle_logs(log)


def check_containers():
    docker_tag_list = {}
    log = {
        "suite": "Docker Container",
        "step": "started"
    }
    handle_logs(log)

    for container_log in containers_build_and_push_all.start():
        if container_log["test"].lower() == "return":
            docker_tag_list = container_log["docker_tag_list"]
        else:
            handle_logs(container_log)

    log = {
        "suite": "Docker Container",
        "suite_done": True,
    }
    handle_logs(log)
    return docker_tag_list


def check_charts(docker_tag_list=[]):
    docker_containers_used = {}
    log = {
        "suite": charts_build_and_push_all.suite_tag,
        "step": "started"
    }
    handle_logs(log)

    for chart_log in charts_build_and_push_all.start(p_user=username, p_pwd=password):
        if chart_log["test"].lower() == "return":
            docker_containers_used = chart_log["docker_containers_used"]
        else:
            handle_logs(chart_log)

    log = {
        "suite": charts_build_and_push_all.suite_tag,
        "suite_done": True,
    }
    handle_logs(log)
    return docker_containers_used


def build_and_push_containers():
    


def start_os_instance(instance_name=instance_name, suite_name="Test Server Instance", os_image=os_image):
    return_value, logs = ci_playbooks.start_os_instance(username=username,
                                                        password=password,
                                                        instance_name=instance_name,
                                                        project_name=os_project_name,
                                                        project_id=os_project_id,
                                                        os_image=os_image,
                                                        volume_size=volume_size,
                                                        instance_flavor=instance_flavor,
                                                        ssh_key=ssh_key,
                                                        test_suite_name=suite_name)
    for log in logs:
        handle_logs(log)

    return return_value


def install_dependencies(target_hosts, suite_name="Install Server Dependencies", os_image=os_image):
    print("target_hosts: {}".format(target_hosts))
    print("suite_name: {}".format(suite_name))
    return_value, logs = ci_playbooks.start_install_server_dependencies(target_hosts=target_hosts, remote_username=os_image, suite_name=suite_name)
    for log in logs:
        handle_logs(log)

    return return_value


def deploy_platform(target_hosts, platform_name, suite_name="Deploy Platform", os_image=os_image):
    return_value, logs = ci_playbooks.deploy_platform(target_hosts=target_hosts, remote_username=os_image, gitlab_username=gitlab_username, gitlab_password=gitlab_password, gitlab_registry=gitlab_registry, platform_name=platform_name)
    for log in logs:
        handle_logs(log)

    return return_value


def start_ui_tests(target_hosts, platform_name, suite_name="UI Tests"):
    for log in platform_ui_tests.start(platform_urls=target_hosts, test_suite_name=suite_name, test_name="{0: <14}: UI TESTS".format(platform_name)):
        handle_logs(log)

    return True


def test_platform_version(target_hosts, platform_name):
    result = deploy_platform(target_hosts=target_hosts, platform_name=platform_name) # if result != "FAILED" else "FAILED"
    result = start_ui_tests(target_hosts=target_hosts, platform_name=platform_name) if result != "FAILED" else "FAILED"
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


def delete_os_instance(instance_name=instance_name, suite_name="Test Server Instance",):
    return_value, logs = ci_playbooks.delete_os_instance(
        username=username, password=password, instance_name=instance_name, suite_name=suite_name, os_project_name=os_project_name, os_project_id=os_project_id)
    for log in logs:
        handle_logs(log)

    return return_value


def delete_ci_instances(suite_name="Delete CI Instances"):
    for key, val in ci_servers.items():
        delete_os_instance(
            instance_name=val["instance_name"], suite_name=suite_name)


def startup_sequence(os_image):
    suite_name = "Test Server Startup"
    # instance_name = "{}-test-server".format(os_image).lower()

    recreated = delete_os_instance(
        instance_name=instance_name,
        suite_name=suite_name
    ) if delete_instances else "SKIPPED"

    server_ip = start_os_instance(
        instance_name=instance_name,
        os_image=os_image,
        suite_name=suite_name
    )
    print(ci_servers)
    if server_ip != "FAILED":
        ci_servers[os_image] = {
            "instance_name": instance_name,
            "os_image": os_image,
            "recreated": True if recreated != "SKIPPED" else False,
            "ip": server_ip
        }


def launch():
    global lock_file, rp_service, branch_name, suites, username, password

    username = os.environ.get('CI_USERNAME', username)
    password = os.environ.get('CI_PASSWORD', password)

    if username is None:
        print("Credentials not found.")
        username = input("Registry username: ")

    if password is None:
        print("User: {}".format(username))
        password = getpass.getpass("password: ")

    if username is None or username == "" or password is None or password == "":
        print("Exiting!")
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
            make_quick_check()

            if not docker_only:
                check_charts()

            if not charts_only:
                check_containers()

            if charts_only or docker_only:
                print("Docker only: {}".format(docker_only))
                print("Charts only: {}".format(charts_only))
                print("DONE.")
                exit(0)

        running_processes = []
        os.chdir(ansible_playbook_dir)
        if not build_only:
            suite_name = "Test Server Startup"
            log = {
                "suite": suite_name,
                "step": "started"
            }
            handle_logs(log)

            if docs_test:
                startup_sequence("centos7")

            # startup_sequence("centos8")
            startup_sequence("ubuntu")

            log = {
                "suite": suite_name,
                "suite_done": True,
            }
            handle_logs(log)

            running_processes = []
            if "centos7" in ci_servers and docs_test:
                suite_name = ci_servers["centos7"]["ip"]
                log = {
                    "suite": suite_name,
                    "step": "started"
                }
                handle_logs(log)

                result = install_dependencies(
                    target_hosts=[ci_servers["centos7"]["ip"]],
                    docs_test=True,
                    suite_name=suite_name
                )

                platform_name = "JIP Release Docs Test"

                result = deploy_platform(
                    target_hosts=[ci_servers["centos7"]["ip"]],
                    platform_name=platform_name,
                    docs_test=True,
                    config_file="jip_release.yaml"
                ) if "centos7" in ci_servers else "FAILED"

                result = start_ui_tests(
                    target_hosts=[ci_servers["centos7"]["ip"]],
                    suite_name=suite_name,
                    platform_name=platform_name
                ) if result != "FAILED" else "FAILED"

                result = purge_filesystem(
                    target_hosts=[ci_servers["centos7"]["ip"]],
                    config_file="jip_release.yaml",
                    platform_name=platform_name,
                    suite_name=suite_name
                ) if result != "FAILED" else "FAILED"

                log = {
                    "suite": ci_servers["centos7"]["ip"],
                    "suite_done": True
                }
                handle_logs(log)

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
    parser.add_argument("-in", "--inst-name", dest="inst_name", default="kaapana CI Test", help="Name for the CI-instance")
    parser.add_argument("-b", "--branch", dest="branch", default=None, help="Branch to run the CI on. !!CAUTION: will reset the git repo to last commit!")
    parser.add_argument("-dsm", "--disable-safe-mode", dest="disable_safe_mode", default=False, action='store_true',help="Disable safe-mode")
    parser.add_argument("-u", "--username", dest="username", default="kaapana-ci", help="Openstack Username")
    parser.add_argument("-p", "--password", dest="password", default=None, required=False, help="Openstack Password")
    parser.add_argument("-ugl", "--gitlab-username", dest="gitlab_username", default=None, help="GitLab Username")
    parser.add_argument("-pgl", "--gitlab-password", dest="gitlab_password", default=None, help="GitLab Password")
    parser.add_argument("-rgl", "--gitlab-registry", dest="gitlab_registry", default=None, help="GitLab Registry Link")
    parser.add_argument("-di", "--delete-instances", dest="delete_instances", default=False, action='store_true', help="Should a new OS CI instance be created for the tests?")
    parser.add_argument("-en", "--email-notifications", dest="mail_notify", default=False, action='store_true', help="Enable e-mail notifications for errors.")
    parser.add_argument("-bo", "--build-only", dest="build_only", default=False, action='store_true', help="No platform deployment and UI tests.")
    parser.add_argument("-co", "--charts-only", dest="charts_only", default=False, action='store_true', help="Just build all helm charts.")
    parser.add_argument("-do", "--docker-only", dest="docker_only", default=False, action='store_true', help="Just build all Docker containers charts.")
    parser.add_argument("-dr", "--disable-report", dest="disable_report", default=False, action='store_true', help="Disable report to ReportPortal.")
    parser.add_argument("-depo", "--deployment-only", dest="dpl_only", default=False, action='store_true', help="Only deployment tests.")
    parser.add_argument("-allp", "--all-platforms", dest="all_platforms", default=False, action='store_true', help="Test all platforms.")
    parser.add_argument("-dt", "--docs-test", dest="docs_test", default=False, action='store_true', help="Test of the online documentation scripts?")

    args = parser.parse_args()
    branch = args.branch
    disable_safe_mode = args.disable_safe_mode
    delete_instances = args.delete_instances
    username = args.username if args.username is not None else username
    password = args.password if args.password is not None else password
    gitlab_username = args.gitlab_username if args.gitlab_username is not None else gitlab_username 
    gitlab_password = args.gitlab_password if args.gitlab_password is not None else gitlab_password
    gitlab_registry = args.gitlab_registry if args.gitlab_registry is not None else gitlab_registry
    mail_notification = args.mail_notify
    docs_test = args.docs_test
    build_only = args.build_only
    charts_only = args.charts_only
    docker_only = args.docker_only
    dpl_only = args.dpl_only
    disable_report = args.disable_report
    all_platforms = args.all_platforms
    launch_name = launch_name
    instance_name = instance_name if instance_name is not None else args.inst_name
    os_project_name = os_project_name
    os_project_id = os_project_id
    start_parameters = start_parameters
    volume_size = volume_size
    instance_flavor = instance_flavor
    ssh_key = ssh_key

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
