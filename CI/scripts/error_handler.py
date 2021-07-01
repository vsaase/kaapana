import smtplib
import git
import os
import json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


kaapana_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
g = git.Git(kaapana_dir)


def send_email(mail_address, message, logs_dict={}):
    print("++++++++++++++++++++++++++++++++++++++++++++++++++++")
    print("SENDING EMAIL: {}".format(mail_address))
    print("MESSAGE: {}".format(message))
    print("++++++++++++++++++++++++++++++++++++++++++++++++++++")
    from_address = "CI@kaapana.dkfz"
    sending_ts = datetime.now()

    sub = 'kaapana CI report'

    msg = MIMEMultipart('alternative')
    msg['From'] = from_address
    msg['To'] = mail_address
    msg['Subject'] = sub

    body = message
    msg.attach(MIMEText(body, 'html'))

    attachment = MIMEText(json.dumps(logs_dict, indent=4, sort_keys=True))
    attachment.add_header('Content-Disposition', 'attachment', filename="logs.txt")
    msg.attach(attachment)

    s = smtplib.SMTP(host='mailhost2.dkfz-heidelberg.de', port=25)
    s.send_message(msg)
    s.quit()
    return 0


def notify_maintainers(logs_dict):
    print("notify_maintainers: ")
    if "container" in logs_dict:
        maintainers = logs_dict["container"].maintainers
        del logs_dict["container"]
    else:
        maintainers = blame_last_edit(logs_dict)

    if maintainers is None:
        print("++++++++++++++++++++++ COULD NOT EXTRACT MAINTAINER!")
        return
    else:
        print("FILE MAINTAINERS: ")
        print(json.dumps(maintainers, indent=4, sort_keys=True))

    for maintainer in maintainers.keys():
        print("Maintainer: {} -> {}".format(maintainer, maintainers[maintainer]))
        maintainer_name = maintainer
        maintainer_email = maintainers[maintainer]

        error_filepath = os.path.dirname(logs_dict['rel_file']).replace("/home/ubuntu", "")

        message = """
            <html>
                <head></head>
                <body>
                    Hi <b>{}</b>,<br><br>

                    we found some issues within: <b> {} </b>.<br>
                    Since you are the last editor, please have a look at it.<br>
                    Thanks!<br><br>
                    sincerely yours,<br>
                    JIPCI <br>
                </body>
            </html>
            """.format(maintainer_name, error_filepath)

        send_email(mail_address=maintainer_email, message=message, logs_dict=logs_dict)


def blame_last_edit(logs_dict):
    error_filepath = os.path.dirname(logs_dict['rel_file'])
    print("Git blame path: {}".format(error_filepath))
    if error_filepath == "" and error_filepath is None and not os.path.isfile(error_filepath) or not os.path.isdir(error_filepath):
        print("error_filepath is not a valid file or dir! -> return")
        return None

    git_log = g.log("-s", "-n1", "--pretty=format:%an %ae%n", "--", error_filepath)
    if len(git_log.split(" ")) != 3:
        print("############################################# Could not extract last editor: {}".format(git_log))
        return None

    firstname, lastname, email_address = git_log.split(" ")
    print("Git Last editor: {} {}".format(firstname, lastname))
    print("Git mail address: {}".format(email_address))

    return {"{} {}".format(firstname, lastname): email_address}


if __name__ == '__main__':
    # send_email(mail_address="jonas.scherer@dkfz-heidelberg.de", message="Here is a test message!")
    blame_last_edit("/home/jonas/projects/kaapana/workflows/docker-container/", logs_dict={"ERROR": "error."})
