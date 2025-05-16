#!/bin/bash

LOG_PARAMS="--log.all_level=debug"

PORT_ARGS="tx_port=tcp://*:2301,rx_port=tcp://localhost:2300"
ZMQ_ARGS="--rf.device_name=zmq --rf.device_args=\"${PORT_ARGS},id=ue3,base_srate=23.04e6\" --gw.netns=ue3"


## Create netns for UE
ip netns list | grep "ue3" > /dev/null
if [ $? -eq 1 ]; then
  echo creating netspace ue3...
  sudo ip netns add ue3
  if [ $? -ne 0 ]; then
   echo failed to create netns ue3
   exit 1
  fi
fi

sudo ../build/srsue/src/srsue ue3.conf ${LOG_PARAMS} ${ZMQ_ARGS} --rat.eutra.dl_earfcn=3350 --delay.time 2 "$@"