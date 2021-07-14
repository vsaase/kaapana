import os
import sys
import getpass
from argparse import ArgumentParser
import traceback
import json

kaapana_int_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
scripts_dir = os.path.join(kaapana_int_dir, "CI", "scripts")
playbook_dir = os.path.join(kaapana_int_dir, "CI", "ansible_playbooks")
sys.path.insert(1, scripts_dir)
import ci_playbooks

# defaults
os_image = "ubuntu"
volume_size = "90"
instance_flavor = "dkfz-8.16"
ssh_key = None
os_project_name = None
os_project_id = None
instance_name = "kaapana-ci-depl-server"
username = None
password = None
gitlab_username = None
gitlab_password = None
gitlab_project = None # e.g. "kaapana/kaapana"
delete_instance = False
debug_mode = False

def handle_logs(logs):
    global debug_mode
    for log in logs:
        if "loglevel" in log and log["loglevel"].lower() != "info":
            print(json.dumps(log, indent=4, sort_keys=True))
            exit(1)
        elif debug_mode:
            print(json.dumps(log, indent=4, sort_keys=True))

def start_os_instance():
    return_value, logs = ci_playbooks.start_os_instance(username=username,
                                                        password=password,
                                                        instance_name=instance_name,
                                                        project_name=os_project_name,
                                                        project_id=os_project_id,
                                                        os_image=os_image,
                                                        volume_size=volume_size,
                                                        instance_flavor=instance_flavor,
                                                        ssh_key=ssh_key)
    return return_value


def install_server_dependencies(target_hosts):
    return_value, logs = ci_playbooks.start_install_server_dependencies(target_hosts=target_hosts, remote_username=os_image, suite_name="Get new instance")
    handle_logs(logs)
    return return_value


def deploy_platform(target_hosts):
    return_value, logs = ci_playbooks.deploy_platform(target_hosts=target_hosts, remote_username=os_image, gitlab_username=gitlab_username, gitlab_password=gitlab_password, gitlab_project=gitlab_project, platform_name="Kaapana platform")
    handle_logs(logs)

    return return_value


def remove_platform(target_hosts):
    return_value, logs = ci_playbooks.delete_platform_deployment(target_hosts=target_hosts, platform_name="Kaapana platform")
    handle_logs(logs)

    return return_value


def purge_filesystem(target_hosts):
    return_value, logs = ci_playbooks.purge_filesystem(target_hosts=target_hosts, platform_name="Kaapana platform")
    handle_logs(logs)

    return return_value


def delete_os_instance():
    return_value, logs = ci_playbooks.delete_os_instance(username=username, password=password, instance_name=instance_name, os_project_name=os_project_name, os_project_id=os_project_id)
    handle_logs(logs)

    return return_value

def print_success(host):
    print("""
    The installation was successfull!

    visit https://{}

    Default user credentials:
    username: kaapana
    password: kaapana

    """.format(host))
    
    return "OK"

def launch():
    global os_image, volume_size, instance_flavor, ssh_key, os_project_name, instance_name, username, password, gitlab_username, gitlab_password, gitlab_project

    os.chdir(playbook_dir)
    if username is None:
        username_template = "jip-ci-kaapana"
        username = input("OpenStack username [{}]:".format(username_template))
        username = username_template if (username is None or username == "") else username

    if password is None:
        password = getpass.getpass("OpenStack password: ")
    
    if gitlab_username is None:
        gitlab_username = input("GitLab username:")
        # TODO: throw error if no input from user

    if gitlab_password is None:
        gitlab_password = getpass.getpass("GitLab password: ")

    if os_project_name is None:
        os_project_template = "E230-DKTK-JIP"
        os_project_name = input("OpenStack project [{}]:".format(os_project_template))
        os_project_name = os_project_template if (os_project_name is None or os_project_name == "") else os_project_name
    
    if gitlab_project is None:
        gitlab_project_template = "kaapana/kaapana"
        gitlab_project = input("OpenStack project [{}]:".format(gitlab_project_template))
        gitlab_project = gitlab_project_template if (gitlab_project is None or gitlab_project == "") else gitlab_project

    if instance_name is None:
        instance_name_template = "{}-kaapana-instance".format(getpass.getuser())
        instance_name = input("OpenStack instance name [{}]:".format(instance_name_template))
        instance_name = instance_name_template if (instance_name is None or instance_name == "") else instance_name

    result = delete_os_instance() if delete_instance else "SKIPPED"
    instance_ip_address = start_os_instance()
    result = install_server_dependencies(target_hosts=[instance_ip_address]) if instance_ip_address != "FAILED" else "FAILED"
    result = deploy_platform(target_hosts=[instance_ip_address]) if result != "FAILED" else "FAILED"
    result = print_success(instance_ip_address) if result != "FAILED" else "FAILED"


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("-u", "--username", dest="username", default=None, help="OpenStack Username")
    parser.add_argument("-p", "--password", dest="password", default=None, required=False, help="OpenStack Password")
    parser.add_argument("-ugl", "--gitlab-username", dest="gitlab_username", default=None, help="GitLab Username")
    parser.add_argument("-pgl", "--gitlab-password", dest="gitlab_password", default=None, required=False, help="GitLab Password")
    parser.add_argument("-pjgl", "--gitlab-project", dest="gitlab_project", default=None, required=False, help="GitLab Project Name")
    parser.add_argument("-di", "--delete-instance", dest="delete_instance", default=None,  action='store_true', help="Delete existing instance first?")
    parser.add_argument("-in", "--instance-name", dest="instance_name", default=None, help="Name for the OpenStack instance?")
    parser.add_argument("-osp", "--os-project-name", dest="os_project_name", default=None, help="Which OpenStack project should be used?")
    parser.add_argument("-osid", "--os-project-id", dest="os_project_id", default=None, help="What is the ID of the OpenStack project?")
    parser.add_argument("-vol", "--volume-size", dest="os_vol_size", default=None, help="OS volume size in GB?")
    parser.add_argument("-fla", "--flavor", dest="os_flavor", default=None, help="OS flavor eg. 'dkfz-8.16' ?")
    parser.add_argument("-key", "--ssh-key", dest="os_ssh_key", default=None, help="Name of the OS ssh-key?")
    parser.add_argument("-img", "--image", dest="os_image", default=None, help="Which OS image should be used eg '' ?")

    args = parser.parse_args()
    delete_instance = args.delete_instance if args.delete_instance is not None else delete_instance
    username = args.username if args.username is not None else username 
    password = args.password if args.password is not None else password
    gitlab_username = args.gitlab_username if args.gitlab_username is not None else gitlab_username 
    gitlab_password = args.gitlab_password if args.gitlab_password is not None else gitlab_password
    gitlab_project = args.gitlab_project if args.gitlab_project is not None else gitlab_project
    instance_name = args.instance_name if args.instance_name is not None else instance_name
    volume_size = args.os_vol_size if args.os_vol_size is not None else volume_size
    instance_flavor = args.os_flavor if args.os_flavor is not None else instance_flavor
    ssh_key = args.os_ssh_key if args.os_ssh_key is not None else ssh_key
    os_project_name = args.os_project_name if args.os_project_name is not None else os_project_name
    os_image = args.os_image if args.os_image is not None else os_image

    launch()
