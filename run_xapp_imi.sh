#!/bin/bash

cd /home/azuka/spectrumsharing_4g/radarxApp/
python3 radar.py &
cd ..
cd /home/azuka/spectrumsharing_4g/imi/
python3 imi.py &
cd ..
sleep 2