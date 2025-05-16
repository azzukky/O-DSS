#!/bin/bash

LOG_ARGS="--log.all_level=debug"


OTHER_ARGS="--enb_files.rr_config=rr1.conf"

sudo ../build/srsenb/src/srsenb enb.conf ${LOG_ARGS} ${OTHER_ARGS} $@
