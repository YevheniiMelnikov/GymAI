import os

# local
RESOURCES = {
    "messages": f"{os.getcwd()}/texts/messages.yml",
    "buttons": f"{os.getcwd()}/texts/buttons.yml",
    "commands": f"{os.getcwd()}/texts/commands.yml",
}

# docker
# RESOURCES = {
#     "messages": "/opt/texts/messages.yml",
#     "buttons": "/opt/texts/buttons.yml",
#     "commands": "/opt/texts/commands.yml",
# }
