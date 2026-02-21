# `hw` CLI Tool

The `hw` CLI tool encapsulates the various automations I built for designing hardware systems.

## Stack

- Click: https://github.com/pallets/click?tab=readme-ov-file

## Structure

- Root `hw` command
    - DOMAIN: a domain is a container of tool. `ee` may house tools for circuit design and analysis for example.
        - TOOL: a tool is a container of commands, i.e., a hammer is a tool, hammering a nail is a command, pulling out a nail is another ocmmanad
            - COMMAND: a traditional cli command