#!/bin/bash

LOG_PARAMS="--log.all_level=debug"

PORT_ARGS="tx_port=tcp://*:2101,rx_port=tcp://localhost:2100"
ZMQ_ARGS="--rf.device_name=zmq --rf.device_args=\"${PORT_ARGS},id=ue1,base_srate=23.04e6\" --gw.netns=ue1"


## Create netns for UE
ip netns list | grep "ue1" > /dev/null
if [ $? -eq 1 ]; then
  echo creating netspace ue1...
  sudo ip netns add ue1
  if [ $? -ne 0 ]; then
   echo failed to create netns ue1
   exit 1
  fi
fi

# sudo ../build/srsue/src/srsue ue1.conf  --rat.eutra.dl_earfcn=3350 "$@"

sudo ../build/srsue/src/srsue ue1.conf ${LOG_PARAMS} ${ZMQ_ARGS} --rat.eutra.dl_earfcn=3350 "$@"