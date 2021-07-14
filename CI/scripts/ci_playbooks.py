#!/usr/bin/python3

import os
import ci_playbook_execute
import json
from pathlib import Path

kaapana_home = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.realpath(__file__))))


def start_os_instance(username, password, instance_name="kaapana-deploy-instance", project_name="E230-DKTK-JIP", project_id="969831bf53424f1fb318a9c1d98e1941", os_image="centos7", volume_size="90", instance_flavor="dkfz-8.16", ssh_key="kaapana", test_suite_name="Setup Test Server"):
    playbook_path = os.path.join(
        kaapana_home, "CI/ansible_playbooks/00_start_openstack_instance.yaml")
    if not os.path.isfile(playbook_path):
        print("playbook yaml not found.")
        exit(1)

    extra_vars = {
        "os_project_name": project_name,
        "os_project_id": project_id,
        "os_instance_name": instance_name,
        "os_username": username,
        "os_password": password,
        "os_image": os_image,
        "os_ssh_key": ssh_key,
        "os_volume_size": volume_size,
        "os_instance_flavor": instance_flavor
    }

    instance_ip_address, logs = ci_playbook_execute.execute(
        playbook_path, testsuite=test_suite_name, testname="Start OpenStack instance: {}".format(os_image), hosts=["localhost"], extra_vars=extra_vars)

    return instance_ip_address, logs


def start_install_server_dependencies_centos(target_hosts, ssh_key=str(Path.home())+"/.ssh/kaapana.pem", test_suite_name="Setup Test Server", docs_test=False):
    if not os.path.isfile(ssh_key):
        print("SSH-key could not be found! {}".format(ssh_key))
        return "FAILED", []

    playbook_path = os.path.join(
        kaapana_home, "CI/ansible_playbooks/02_install_server_dependencies_centos.yaml")
    if not os.path.isfile(playbook_path):
        print("playbook yaml not found.")
        exit(1)

    extra_vars = {
        "KAAPANA_HOME": kaapana_home,
        # "ansible_ssh_private_key_file": ssh_key,
        "doc_install_test": "true" if docs_test else "false"
    }

    return_value, logs = ci_playbook_execute.execute(
        playbook_path, testsuite=test_suite_name, testname="Install Server Dependencies", hosts=target_hosts, extra_vars=extra_vars)
    return return_value, logs


def start_install_server_dependencies(target_hosts, remote_username, suite_name="Setup Test Server"):
    playbook_path = os.path.join(kaapana_home, "CI/ansible_playbooks/01_install_server_dependencies.yaml")
    if not os.path.isfile(playbook_path):
        print("playbook yaml not found.")
        exit(1)

    extra_vars = {
        "remote_username": remote_username
    }

    return_value, logs = ci_playbook_execute.execute(playbook_path, testsuite=suite_name, testname="Install Server Dependencies", hosts=target_hosts, extra_vars=extra_vars)
    return return_value, logs


def deploy_platform(target_hosts, remote_username, gitlab_username, gitlab_password, gitlab_project, platform_name, test_suite_name="Test Platform"):
    playbook_path = os.path.join(
        kaapana_home, "CI/ansible_playbooks/02_deploy_platform.yaml")
    if not os.path.isfile(playbook_path):
        print("playbook yaml not found.")
        exit(1)

    extra_vars = {
        "remote_username": remote_username,
        "gitlab_username": gitlab_username,
        "gitlab_password": gitlab_password,
        "gitlab_project" : gitlab_project
    }

    return_value, logs = ci_playbook_execute.execute(playbook_path, testsuite=test_suite_name, testname="{0: <14}: Deploy platform".format(platform_name), hosts=target_hosts, extra_vars=extra_vars)
    return return_value, logs


def delete_platform_deployment(target_hosts, platform_name, suite_name="Test Platform"):
    global instance_ip_address

    playbook_path = os.path.join(
        kaapana_home, "CI/ansible_playbooks/03_delete_deployment.yaml")
    if not os.path.isfile(playbook_path):
        print("playbook yaml not found.")
        exit(1)

    extra_vars = {
        "KAAPANA_HOME": kaapana_home,
    }

    return_value, logs = ci_playbook_execute.execute(playbook_path, testsuite=suite_name, testname="{0: <14}: Delete platform".format(
        platform_name), hosts=target_hosts, extra_vars=extra_vars)
    return return_value, logs


def purge_filesystem(target_hosts, platform_name, uite_name="Test Platform"):
    playbook_path = os.path.join(
        kaapana_home, "CI/ansible_playbooks/04_purge_filesystem.yaml")
    if not os.path.isfile(playbook_path):
        print("playbook yaml not found.")
        exit(1)

    extra_vars = {
        "server_domain": "",
        "KAAPANA_HOME": kaapana_home,
    }

    return_value, logs = ci_playbook_execute.execute(playbook_path, testsuite=suite_name, testname="{0: <14}: Purge filesystem from".format(
        platform_name), hosts=target_hosts, extra_vars=extra_vars)
    return return_value, logs


def delete_os_instance(username, password, instance_name="kaapana-instance", suite_name="Setup Test Server", os_project_name="E230-DKTK-JIP", os_project_id="969831bf53424f1fb318a9c1d98e1941"):
    playbook_path = os.path.join(
    kaapana_home, "CI/ansible_playbooks/05_delete_os_instance.yaml")

    if not os.path.isfile(playbook_path):
        print("playbook yaml not found.")
        exit(1)

    extra_vars = {
        "os_project_name": os_project_name,
        "os_project_id": os_project_id,
        "os_username": username,
        "os_password": password,
        "os_instance_name": instance_name
    }

    return_value, logs = ci_playbook_execute.execute(playbook_path, testsuite=suite_name, testname="Delete OpenStack CI instance", hosts=["localhost"], extra_vars=extra_vars)
    return return_value, logs


if __name__ == "__main__":
    print("File execution is not supported at the moment")
    exit(1)
