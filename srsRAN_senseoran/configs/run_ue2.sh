#!/bin/bash

LOG_PARAMS="--log.all_level=debug"

PORT_ARGS="tx_port=tcp://*:2201,rx_port=tcp://localhost:2200"
ZMQ_ARGS="--rf.device_name=zmq --rf.device_args=\"${PORT_ARGS},id=ue2,base_srate=23.04e6\" --gw.netns=ue2"


## Create netns for UE
ip netns list | grep "ue2" > /dev/null
if [ $? -eq 1 ]; then
  echo creating netspace ue2...
  sudo ip netns add ue2
  if [ $? -ne 0 ]; then
   echo failed to create netns ue2
   exit 1
  fi
fi

sudo ../build/srsue/src/srsue ue2.conf ${LOG_PARAMS} ${ZMQ_ARGS} --rat.eutra.dl_earfcn=3350 "$@"
