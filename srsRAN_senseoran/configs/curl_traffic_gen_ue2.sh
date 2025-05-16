#!/bin/bash


while true 
do
	sudo ip netns exec ue2 curl http://10.45.0.1:8000/disk.iso -o a.iso
done
