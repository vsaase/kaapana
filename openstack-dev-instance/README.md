# Please add the kaapana private key to your ssh config!

~/.ssh/config :

Host 10.128.*.*
IdentityFile ~/.ssh/<kaapana-key-name>.pem

# You can set the ENV **CI_PASSWORD** and then skip the **jip-ci-kaapana** password input

Make sure you have the ssh key pair (e.g. kaapana.pem and kaapana.pub) in your ~/.ssh folder
Make sure you have python3 pip package installer, if not do:
    sudo apt install python3-pip
Install requirements from requirements file. E.g. like with the below command:
    sudo python3 -m pip install -r requirements.txt
Run the start_new_os_inst_with_kaapana.py script with the necessary input parameters. You can also use the global variables inside the script to set their values
Check out the script for more details