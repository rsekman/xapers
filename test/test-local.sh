# declare prerequisites for external binaries used in tests
test_declare_external_prereq python3

export HOME="$TEST_DIRECTORY"

export PYTHONPATH="$TEST_DIRECTORY"/..:$PYTHONPATH
alias xapers="python3 -m xapers"

export DOC_DIR="$TEST_DIRECTORY/docs"

export XAPERS_ROOT="$TMP_DIRECTORY/docs"
