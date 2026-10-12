This is an addendum to the primary AGENTS.md located in the MeerK40t project root and is specific to the ruida_pa driver.

## Ruida PA Driver (ruida_pa) Development
- The focus is development of the ruida_pa driver. Because of this it is not necessary to run a complete test suite. Only the tests directly related to the ruida_pa driver are needed.
- The ruida_pa driver depends upon the ruida-pa package which is an upstream project located in `../../opensource/ruida-pa`. Do not modify files in the `../../opensource/ruida-pa` directory tree. NOTE: At some point in the future the ruida-pa package will be installed from PyPi.
- The Ruida driver in `meerk40t/ruida` is a prototype and is for reference only. Never modify files in the `meerk40t/ruida` directory tree.
- The Ruida driver (ruida_pa) in development is in driver directory located at `meerk40t/ruida_pa`. In the following all files and other directories are relative to the driver directory unless specified differently.
- All edits must be confined to the driver directory and its subdirectories with the exceptions of ruida_pa specific tests in `test/test_drivers_ruida_pa.py` and the `dev` directory (described below). All additional ruida_pa unit tests are in `test`.
- Temporary files should be created in `tmp`. The files contained in this directory will be purged regularly.
- The `dev` directory is a symbolic link to a directory outside the `meerk40t` project tree. Permission is granted to write to this directory and its subdirectories as needed.
- If changes outside ruida_pa are needed, write a prompt which can passed to the upstream maintainers for either MeerK40t or the ruida-pa package. Save the prompt in `dev/prompts` using a simple but descriptive file name.
- These files are needed for development and revision control using git:
    - `commit.txt`: To be written to `dev/commit.txt` only when the user requests it (e.g. "Write a new commit.txt"). Changes since the last commit are documented as summary lines in this file. Multiple summary lines are used when more than one issue (i.e. new feature or problem fix) has been resolved in a single commit. NOTE: Each issue should have only one line. Change details are to be written to the testing log (below). Each summary line should be prefixed a word indicating the nature of the change. These are:
        - `feature:` A new feature has been added.
        - `enhancement:` An existing feature has been improved.
        - `fix:` A problem has been fixed.
    - `PR.md`: To be written to `dev/PR.md` only when the user requests it. This file contains a description of changes in a PR to be submitted to the upstream MeerK40t project.
    - `iteration.txt`: This file contains the development iteration number (`<iteration>`) and is maintained as `dev/iteration.txt`. This file contains the current development iteration number. If this file does not exist initialize it to "1". The iteration number is incremented AFTER writing a new `PR.md` (e.g. "1" is incremented to "2").
    - Development logs are maintained in `dev/logs` and have names formatted as `ruida_pa-dev-<iteration>.md`. A new development log is started when the iteration number is incremented. Each issue is documented within a different section named for the issue being described and contains the following subsections:
        - **Problem**: Describes the issue being documented. This can be a problem needing a fix or a new feature.
        - **Solution**: Describes the solution(s) needed to resolve the problem.
        - **Verification**: Actions taken to verify the solution resolves the problem.
    Individual details within each section should be documented using bullet lists to improve readability. The development log for the current iteration is to be updated when `commit.txt` is written.

After reading this document emit a message to the console to inform the user that it has been read.