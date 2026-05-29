EXIT_COMMANDS = {"/exit", "/quit"}


def is_exit_command(user_input):
    return user_input in EXIT_COMMANDS
