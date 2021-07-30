import os
import json
import glob
import charts_build_and_push_all
import containers_build_and_push_all

kaapana_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
airflow_components_path = os.path.join(kaapana_path, "workflows")
registry_prefix = "dktk-jip-registry.dkfz.de"


def get_container_usage():
    global airflow_components_path
    containers_used = {}

    python_files = glob.glob(airflow_components_path+"/**/*.py", recursive=True)
    python_files_count = len(python_files)

    print("Found {} python_files".format(len(python_files)))

    for python_file in python_files:
        with open(python_file, "r") as py_content:
            for line in py_content:
                line = line.rstrip()
                if registry_prefix in line and "#" not in line:
                    docker_container = registry_prefix+line.split(registry_prefix)[1].replace(" ", "").replace("\"", "").replace("'", "").replace(",", "").replace("version=", ":").replace(")", "")
                    if docker_container not in containers_used.keys():
                        containers_used[docker_container] = python_file
    return containers_used


def complete_quick_check():
    af_docker_containers = get_container_usage()

    log_entry = {
        "suite": "Quick Check",
        "nested_suite": charts_build_and_push_all.suite_tag,
    }
    yield log_entry

    for log in charts_build_and_push_all.quick_check():
        if type(log) == dict:
            yield log
        else:
            build_ready_list, containers_used = log

    log_entry = {
        "suite": charts_build_and_push_all.suite_tag,
        "suite_done": True
    }
    yield log_entry

    containers_used.update(af_docker_containers)

    log_entry = {
        "suite": "Quick Check",
        "nested_suite": containers_build_and_push_all.suite_tag,
    }
    yield log_entry

    for log in containers_build_and_push_all.quick_check():
        if type(log) == dict:
            yield log
        else:
            docker_containers_list = log

    log_entry = {
        "suite": containers_build_and_push_all.suite_tag,
        "suite_done": True
    }
    yield log_entry

    containers_built = {}
    base_images_used = {}
    log_entry = {
        "suite": "Quick Check",
        "nested_suite": "CI_IGNORE",
    }
    yield log_entry
    for container in docker_containers_list:
        if container.ci_ignore:
            print("CI ignore!")
            log_entry = {
                "suite": "CI_IGNORE",
                "test": "{}".format(container.tag.replace(registry_prefix, "")),
                "step": "CI_IGNORE",
                "log": "",
                "loglevel": "WARN",
                "message": "enabled!",
                "rel_file": container.path,
            }
            yield log_entry
        else:
            containers_built[container.tag] = container.path
            for base_image in container.base_images:
                if registry_prefix in base_image:
                    base_images_used[base_image] = "BASE_IMAGE: {}".format(container.path)

    log_entry = {
        "suite": "CI_IGNORE",
        "suite_done": True
    }
    yield log_entry

    containers_used.update(base_images_used)

    suite_tag_used_built = "Container Used vs Built"
    log_entry = {
        "suite": "Quick Check",
        "nested_suite": suite_tag_used_built,
    }
    yield log_entry

    usage_vs_build_tag="Usage vs Built"
    for container_used in containers_used.keys():
        if container_used in containers_built.keys():
            log = {
                "suite": suite_tag_used_built,
                "test": "{}".format(container_used.replace(registry_prefix, "")),
                "step": usage_vs_build_tag,
                "log": "",
                "loglevel": "DEBUG",
                "message": "Container was built and used!",
                "rel_file": containers_used[container_used],
            }
            del containers_built[container_used]

        else:
            log = {
                "suite": suite_tag_used_built,
                "test": "{}".format(container_used.replace(registry_prefix, "")),
                "step": usage_vs_build_tag,
                "log": "",
                "loglevel": "WARN",
                "message": "Container was used but not built!",
                "rel_file": containers_used[container_used],
            }
        yield log
    log_entry = {
        "suite": suite_tag_used_built,
        "suite_done": True
    }
    yield log_entry

    suite_tag_used_built = "Container Built vs Used"
    log_entry = {
        "suite": "Quick Check",
        "nested_suite": suite_tag_used_built,
    }
    yield log_entry

    build_vs_usage_tag="Built vs Usage"
    if len(containers_built.keys()) == 0:
        log = {
            "suite": suite_tag_used_built,
            "test": "{}".format(container_used.replace(registry_prefix, "")),
            "step": build_vs_usage_tag,
            "log": "",
            "loglevel": "DEBUG",
            "message": "All built containers are used",
            "rel_file": "",
        }
        yield log

    else:
        for container_left in containers_built.keys():
            log = {
                "suite": suite_tag_used_built,
                "test": "{}".format(container_left.replace(registry_prefix, "")),
                "step": build_vs_usage_tag,
                "log": "",
                "loglevel": "WARN",
                "message": "Container was built but never used!",
                "rel_file": containers_built[container_left],
            }
            yield log

    log_entry = {
        "suite": suite_tag_used_built,
        "suite_done": True
    }
    yield log_entry


if __name__ == '__main__':
    for log in complete_quick_check():
        if type(log) == dict:
            print(json.dumps(log, sort_keys=True, indent=4))
            if log['loglevel'].lower() == "error":
                print("ERROR! +++++++++++++++++++++++++++++++++++++++++++++++++")

    print("DONE")
