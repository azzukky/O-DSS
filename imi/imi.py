import sctp, socket
import time
from datetime import datetime
from log import *
import threading
import os
import numpy as np
import struct
import array
import matplotlib
import matplotlib.pyplot as plt
matplotlib.use('Agg')  
import numpy as np
from PIL import Image
from datetime import datetime
from ricsdl.syncstorage import SyncStorage
import io
import redis
import json



sampling_rates = [7.68e6, 15.36e6]
SAMPLING_RATE = sampling_rates[1]
spectrogram_time = 0.005 # 10 ms
num_of_samples = SAMPLING_RATE * spectrogram_time
spectrogram_size = num_of_samples * 8  # size in bytes, where 8 bytes is the size of one sample (complex64)

# This is for redis
ns1 = "Spectrograms"
ns2 = "Kpms"
sdl1 = SyncStorage()

ENB_COUNT = 1
server = None
command = b'k'
prev_iq_data = None
command_prev = None
iq_samples = {}
lock = threading.Lock()

def post_init(self):
    global server, spec_conn, xapp_conn

    # This will automatically find a correct IP address to use, and works well in the RIC.
    ip_addr = socket.gethostbyname(socket.gethostname())
    # ip_addr = "127.0.1.1"
    port_srsRAN = 5000 # local port to enable connection to srsRAN
    port_specxApp = 5001
    port_radarxApp = 5002
    # port_malxApp = 5003

    log_info( f"E2-like enabled, connecting using SCTP on {ip_addr}")
    server = sctp.sctpsocket_tcp(socket.AF_INET)
    server.bind((ip_addr, port_srsRAN)) 
    server.listen()

    log_info('Server started')

    # Create client connection
    spec_conn = sctp.sctpsocket_tcp(socket.AF_INET)
    xapp_conn = sctp.sctpsocket_tcp(socket.AF_INET)

    # while True:
    #     try:
    #         spec_conn.connect((os.getenv('SPEC_ADDR', ip_addr), port_specxApp))
    #         break
    #     except:
    #         log_info("Waiting for specxApp to start...")
    #         time.sleep(1)

    
    while True:
        try:
            xapp_conn.connect((os.getenv('XAPP_ADDR', ip_addr), port_radarxApp))
            break
        except:
            log_info("Waiting for radarxApp to start...")
            time.sleep(1)

    log_info("Client connection established to radarxApp")


def handle_clients(client_soc, addr, thread_id):
    # This is used to interact with all client base stations
    global prev_iq_data
    try:
        j = 0
        k = 0
        while True:
            try:
                client_soc.send(command)
                # print("Sending command to base station", command)
                print(f"[{thread_id}]    Sending control {command} to srsRAN through e2 lite interface by port {addr[1]}")
                if command == b"k" or len(command) == 8:
                    # For KPMs
                    kpms_header_data = client_soc.recv(20)
                    # timestamp, base_station_id, num_ues = struct.unpack("<dIq", kpms_data)
                    timestamp, base_station_id, num_ues = process_kpms(kpms_header_data)
                    print(f"[{timestamp}] {hex(base_station_id)} and {num_ues} UEs")
                    print(len(kpms_header_data))

                    # Now that we know the number of UE metrics, we can retrieve them
                    kpms_payload_data = client_soc.recv(80 * num_ues)
                    ue_metrics = process_kpms(kpms_payload_data,num_ues=num_ues)
                    # print(f"Found length of data: {len(ue_metrics)}")
                    # print(f"All metrics {ue_metrics}")
                    if ue_metrics:
                        for i, ue in enumerate(ue_metrics):
                            print(f"UE {i+1} Metrics:")
                            print(f"  RNTI: {ue[0]}")
                            print(f"  PUSCH SINR: {ue[1]}")
                            print(f"  PUCCH SINR: {ue[2]}")
                            print(f"  RSSI: {ue[3]}")
                            print(f"  Turbo Iterators: {ue[4]}")
                            print(f"  UL MCS: {ue[5]}")
                            print(f"  UL Num Samples: {ue[6]}")
                            print(f"  DL MCS: {ue[7]}")
                            print(f"  DL Num Samples: {ue[8]}")
                            print(f"  TX Packets: {ue[9]}")
                            print(f"  TX Errors: {ue[10]}")
                            print(f"  TX Bitrate: {ue[11]}")
                            print(f"  TX Block Error Rate: {ue[12]}")
                            print(f"  RX Packets: {ue[13]}")
                            print(f"  RX Errors: {ue[14]}")
                            print(f"  RX Bitrate: {ue[15]}")
                            print(f"  RX Block Error Rate: {ue[16]}")
                            print(f"  UL Buffer: {ue[17]}")
                            print(f"  DL Buffer: {ue[18]}")
                            print(f"  DL CQI: {ue[19]}")
                            print("-" * 40)
                        # Next is to save the data into a database for all UEs
                        # if num_ues > 0:
                        kpms_handler(timestamp, base_station_id, num_ues, ue_metrics, k)
                        k+=1
                        if k >= 100:
                            log_info(f"Index reached 100. Flushing the database and resetting index to 0.")
                            flush_database()
                            k = 0
                    
                elif command == b"i":
                    # For I/Q samples
                    i = 0
                    iqdata = client_soc.recv(10000) #conn.recv(10000)
                    # print(f"[{thread_id}]    Receiving I/Q iqdata... from port {addr[1]}")
                    while i < spectrogram_size-10000:
                        if spectrogram_size - i > 10000:
                            size = 10000
                            curr_data= client_soc.recv(size) #conn.recv(size)
                            # spec_conn.sctp_send(curr_data)
                            iqdata+=curr_data
                        else:
                            size = spectrogram_size - i
                            curr_data=client_soc.recv(size) #conn.recv(size)
                            # spec_conn.sctp_send(curr_data)
                            iqdata+=curr_data
                        i+=10000
                    # print(f"[{thread_id}]    Length of received iq buffer representing 10ms frame {len(iqdata)} {addr[1]}")
                    current_iq_data = iqdata 
                    if current_iq_data!=prev_iq_data:
                        if addr[1] == 38071:  
                            # I want to save the I/Q samples into a json file here
                            spec = iq_handler(addr[1],j,current_iq_data)
                            # print(spec)
                            print(f"Length of IQ SAMPLES in dictionary {len(iq_samples)}")
                            if len(iq_samples) == 12:
                                # save_iq_tojson("iq_samples.json",iq_samples)
                                print("Saved IQ SAMPLES TO JSON")    
                            j += 1
                        # elif addr[1] == 38072:
                        #     spec = iq_handler(addr[1],k)
                        #     print(spec)
                        #     k += 1
                        prev_iq_data = current_iq_data
                        time.sleep(0.1)
                    # else:
                        # print("IQ DATA FROM RAN UNCHANGED")
                time.sleep(0.01)
            except OverflowError:
                print("Error: Integer overflow in payload calculation")
                continue
    except OSError as e:
        log_error(e)
                
def entry(self):
    global server , conn
    # Initialize the E2-like interface
    post_init(self)
    clients = []

    # Accept number of connections depending on the number of base stations you have
    try:
        # Loop through for any number of connected base stations
        for i in range(ENB_COUNT):
            conn, addr = server.accept()
            log_info(f'Connected to RAN {i+1} by {addr}')
            clients.append([conn,addr, i])
            conn.send(f"E2-lite request at {datetime.now().strftime('%H:%M:%S')}".encode('utf-8'))
            # print( "Sent E2-lite request to port", addr[1])
        # Start a thread for the radarxApp
        print("In the radar thread")
        radar_recvthread = threading.Thread(target=handle_xAppClient, args=(xapp_conn,))
        radar_recvthread.start()
        

        # Start threads for any number of base stations
        threads = [threading.Thread(target=handle_clients, args=(conn[0], conn[1], conn[2])) for conn in clients]
        # Start threads
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        print("Base stations have been served.")

    except OSError as e:
        log_error(e)

# For threading purposes to receive the ic xApp result concurrently.
def handle_xAppClient(connection):
    global command
    while True:
        command = connection.recv(8)
        print(f"Received command {command}")
        # if command:
        #     command_decoded = command.decode()
        #     print(f"Received command {command_decoded}")

def process_image(new_img):
    image_width = 640
    image_height = 640
    crop_size= (80,60,557,425)
    # new_img = new_img.convert('L')
    processed_image = new_img
    processed_image = processed_image.crop(crop_size)
    processed_image = processed_image.resize((image_width, image_height))
    processed_image = np.array(processed_image)
    return processed_image

def iq_to_spectrogram(iq_data, i,sampling_rate=SAMPLING_RATE)-> Image:
    """Convert I/Q data in 1-dimensional array into a spectrogram image as a numpy array
    """
    global iq_samples
    complex_data = np.frombuffer(iq_data, dtype=np.complex64)
    # iq_samples[str(i)] = {
    #     'data': complex_data
    # }
    # print(iq_samples)
    # save_iq_tojson("iq_samples.json",iq_samples)
    # print("Saved IQ SAMPLES TO JSON")
    
    # print(complex_data)
    # print(len(complex_data), 'length of IQ data')
    
    # Create new matplotlib figure
    fig = plt.figure()

    # Create spectrogram from data
    plt.specgram(complex_data, Fs=sampling_rate)
    # Manually update the canvas
    fig.canvas.draw()
    w, h = [int(i) for i in fig.canvas.get_renderer().get_canvas_width_height()]
    plt.close()
    # print("canvas", fig.canvas.tostring_rgb())
    
    # Convert image to bytes, then read as a PIL image and return
    img = Image.frombytes('RGB', (w, h), fig.canvas.tostring_rgb())
    processed_img = process_image(img)
    processed_img = Image.fromarray(np.uint8(processed_img))
    processed_imgtobytes = io.BytesIO()
    prc = processed_img
    prc.save(processed_imgtobytes,format="PNG")
    processed_bytes = processed_imgtobytes.getvalue()
    
    # ret = io.BytesIO(processed_bytes)
    # image = Image.open(ret)
    # arr = np.array(image)
    # print("Converted back")
    # print("Plotting image")
    # plt.imshow(arr)
    # plt.show()
    # plt.close()
    
    return img, processed_bytes   
def iq_handler(ran_id,i,current_iq_data):
    with lock:
        sample, image_bytes= iq_to_spectrogram(current_iq_data,i)
    # save images somewhere on device
    if ran_id == 38071:
        sample.save(f'samples/{i}.png')
        # print(image_bytes, "These are bytes")
        sdl1.set(ns1, {'new_spec': image_bytes})
        # print(sdl1.get(ns1, {'new_spec'}), "This is me checking if they did save")
    # elif ran_id == 38072:
    #     sample.save(f'samples_ran2/{i}.png')
    #     sdl1.set(ns2, {'new_spec2': image_bytes})
    # print(image_bytes)
    # save just latest image to redis database
    
    # print("successfully saved to Redis database")
    return "Completed IQ HANDLER"

def save_iq_tojson(filename, data):
    formatted_data = {}
    required_keys = list(data.keys())[-2:]
    for key in required_keys:
        value = data[key]
        formatted_data[key] = {
            'data': [f'({sample.real}+{sample.imag}j)' for sample in value['data']]
        }
    # Write to JSON file
    with open(filename, 'w') as file:
        json.dump(formatted_data, file, indent=4)

    return "IQ samples saved to json file"
    

def process_kpms(kpms_data, num_ues=None):
    if not isinstance(kpms_data, bytes):
        raise ValueError("Input data must be of type 'bytes'.")
    # Process header (20 bytes)
    if len(kpms_data) == 20:
        try:
            timestamp, base_station_id, num_ues = struct.unpack("<dIq", kpms_data)
            return timestamp, base_station_id, num_ues
        except struct.error as e:
            raise ValueError(f"Failed to unpack header data: {e}")
    # Process UE metrics (80 bytes per UE)
    elif len(kpms_data) % 80 == 0:
        if num_ues is None:
            raise ValueError("num_ues must be provided to process UE metrics.")
        try:
            ue_metrics = []
            # Iterate over the data in chunks of 80 bytes (one chunk per UE)
            for i in range(num_ues):
                start = i * 80
                end = start + 80
                # Check if there's enough data left
                if end > len(kpms_data):
                    raise ValueError(f"Insufficient data for {num_ues} UEs. Expected {num_ues * 80} bytes, got {len(kpms_data)} bytes.")

                ue_data = kpms_data[start:end]

                # Unpack the UE metrics
                ue_metric = struct.unpack("<Hxxfffffifiiiiiiiiiiif", ue_data)
                ue_metrics.append(ue_metric)

            return ue_metrics
        except struct.error as e:
            raise ValueError(f"Failed to unpack UE metrics data: {e}")
    # Handle invalid data length
    else:
        raise ValueError(f"Invalid data length: {len(kpms_data)} bytes. Expected 20 bytes for header or multiples of 80 bytes for UE metrics.")
    
def kpms_handler(timestamp, bs_id, num_ues, ue_metrics,index):
    try:
        # Prepare the KPMs data for storage
        kpm_entry = {
            "timestamp": timestamp,
            "base_station_id": bs_id,
            "num_ues": num_ues,
            "ue_metrics": []
        }
        # Process each UE's metrics
        for ue in ue_metrics:
            ue_metric = {
                "ue_rnti": ue[0],
                "pusch_sinr": ue[1],
                "pucch_sinr": ue[2],
                "rssi": ue[3],
                "turbo_iterators": ue[4],
                "ul_mcs": ue[5],
                "ul_num_samples": ue[6],
                "dl_mcs": ue[7],
                "dl_num_samples": ue[8],
                "tx_packets": ue[9],
                "tx_errors": ue[10],
                "tx_bitrate": ue[11],
                "tx_block_error_rate": ue[12],
                "rx_packets": ue[13],
                "rx_errors": ue[14],
                "rx_bitrate": ue[15],
                "rx_block_error_rate": ue[16],
                "ul_buffer": ue[17],
                "dl_buffer": ue[18],
                "dl_cqi": ue[19]
            }
            kpm_entry["ue_metrics"].append(ue_metric)
        # Use timestamp as the key for time-series storage
        key = f"kpm_{index}"
        # Save the KPM entry to SyncStorage
        # Convert the KPM entry to a JSON string and encode it into bytes
        kpm_entry_bytes = json.dumps(kpm_entry).encode('utf-8')
        # Save the KPM entry to SyncStorage
        sdl1.set(ns2, {key: kpm_entry_bytes})
        # Log success
        log_info(f"Saved KPMs to SyncStorage under namespace: {ns2}, key: {key}")

    except Exception as e:
        # Log any errors that occur
        log_error(f"Failed to save KPMs to SyncStorage: {e}")

def flush_database():
    try:
        # Use the remove_all method to delete all keys under the namespace
        sdl1.remove_all(ns2)
        # Log the flush operation
        log_info(f"Flushed the database. Deleted all keys under namespace: {ns2}")
    except Exception as e:
        log_error(f"Error flushing the database: {e}")

def start(thread=False):
    entry(None)


if __name__ == '__main__':
    start()
