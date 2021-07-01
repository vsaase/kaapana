# Please add the kaapana private key to your ssh config!

~/.ssh/config :

Host 10.128.*.*
IdentityFile ~/.ssh/<kaapana-key-name>.pem

# You can set the ENV **CI_PASSWORD** and then skip the **jip-ci-kaapana** password input