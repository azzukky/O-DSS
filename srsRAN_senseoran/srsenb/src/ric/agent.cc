#include <list>
#include <iterator>

#include "srsran/common/common.h" //May need to include byte_buffer.h
#include "srsran/common/byte_buffer.h" // New library included to support unique_byte_buffer_t
//#include "srslte/common/logger.h" // All the logs need to be changed
//#include "srslte/common/log_filter.h"
//#include "srslte/common/logmap.h"
#include "srsran/srslog/srslog.h"
#include "srsran/common/network_utils.h"

#include <sys/socket.h>
#include <netinet/sctp.h>
#include <netinet/tcp.h>
#include <fstream>

#include "srsenb/hdr/enb.h"
#include "srsenb/hdr/ric/agent_defs.h"
#include "srsenb/hdr/ric/agent.h"
#include "srsenb/hdr/ric/agent_asn1.h"
#include "srsenb/hdr/ric/e2ap.h"
#include "srsenb/hdr/ric/e2ap_handle.h"
#include "srsenb/hdr/ric/e2ap_encode.h"
#include "srsenb/hdr/ric/e2ap_generate.h"
#include "srsenb/hdr/ric/e2sm.h"
#include "srsenb/hdr/ric/e2sm_gnb_nrt.h"
#ifdef ENABLE_RIC_AGENT_KPM
#include "srsenb/hdr/ric/e2sm_kpm.h"
#endif
#ifdef ENABLE_SLICER
#include "srsenb/hdr/ric/e2sm_nexran.h"
#endif
#ifdef ENABLE_SLICER
#include "srsenb/hdr/stack/mac/slicer_test_utils.h"
#endif




// FOR MAC METRICS:
// do the following:
//  srsenb::enb_metrics_t metrics = {};
//  srsenb::enb_metrics_interface->get_metrics(&metrics); // check for success
//  srsenb::mac_metrics_t *mac_m = metrics->stack->mac;
//





namespace ric {

bool e2ap_xer_print;
bool e2sm_xer_print;

agent::agent(srslog::sink& log_sink,
	     srsenb::enb_metrics_interface *enb_metrics_interface_ // Changing from srslte::logger *logger to srslog::log_sink& log_sink_
#ifdef ENABLE_SLICER
	     ,
	     srsenb::enb_slicer_interface *enb_slicer_interface_
#endif
  )
  : log_sink(log_sink), // Initialzing log_sink
    //log.ric(srslog::fetch_basic_logger("RIC", log_sink)), // Change from log.ric.init("RIC", logger) to log.ric(srslog::fetch_basic_logger("RIC", log_sink))
    ric(srslog::fetch_basic_logger("RIC", log_sink)), // Change from log.ric.init("RIC", logger) to log.ric(srslog::fetch_basic_logger("RIC", log_sink))
    e2ap(srslog::fetch_basic_logger("E2AP", log_sink)), // Change from log.e2ap.init("E2AP", logger) to log.e2ap(srslog::fetch_basic_logger("E2AP", log_sink))
    e2sm(srslog::fetch_basic_logger("E2SM", log_sink)), // Change from log.e2sm.init("E2SM", logger) to log.e2sm(srslog::fetch_basic_logger("E2SM", log_sink))

    enb_metrics_interface(enb_metrics_interface_),
#ifdef ENABLE_SLICER
    enb_slicer_interface(enb_slicer_interface_),
#endif
    thread("RIC")
{
  agent_queue = pending_tasks.add_queue(); // changed from agent_queue_id to agent_queue
};

agent::~agent()
{
  stop();
}

int agent::init(const srsenb::all_args_t& args_,
	   srsenb::phy_cfg_t& phy_cfg_,
	   srsenb::rrc_cfg_t rrc_cfg_)
{
  service_model *model;
  std::list<ric::service_model *>::iterator it;
  std::list<ric::ran_function_t *>::iterator it2;
  ric::ran_function_t *func;
  std::string ric_level_copy;

  args = args_;
  phy_cfg = phy_cfg_;
  rrc_cfg = rrc_cfg_;

  save_path = args.phy.save_path;
  tmp_path = args.phy.tmp_path;
  agent_command_path = args.ric_agent.agent_command_path;
  agent_prb_path = args.ric_agent.agent_prb_path;
  rrc_command_path = rrc_cfg.command_path;

// New way of initializing level and max_dump_limit variables
   
  srslog::basic_levels ric_level = srslog::str_to_basic_level(args.ric_agent.log_level);
  //log.ric.set_level(ric_level);
  ric.set_level(ric_level);
  ric.set_hex_dump_max_size(args.ric_agent.log_hex_limit);
  RIC_DEBUG("log_level = %s\n",args.ric_agent.log_level.c_str());
 
  srslog::basic_levels e2ap_level = srslog::str_to_basic_level(args.ric_agent.log_level);
  e2ap.set_level(e2ap_level);
  e2ap.set_hex_dump_max_size(args.ric_agent.log_hex_limit);
  e2ap_xer_print = (ric_level >= srslog::basic_levels::debug); //srslte::LOG_LEVEL_DEBUG changed to srslog::basic_levels::debug  

  srslog::basic_levels e2sm_level = srslog::str_to_basic_level(args.ric_agent.log_level);
  //log.e2sm.set_level(e2sm_level);  
  e2sm.set_level(e2sm_level);
  e2sm.set_hex_dump_max_size(args.ric_agent.log_hex_limit);
  e2sm_xer_print = (e2sm_level >= srslog::basic_levels::debug); //srslte::LOG_LEVEL_DEBUG changed to srslog::basic_levels::debug  

  // Intialize
  enb_id = args.ric_agent.enb_id;
  sched_save_path = args.stack.mac.sched.sched_save_path;
 
// ric_level_copy = std::string(args.ric_agent.log_level);
  // log.ric_level = log.e2ap_level = log.e2sm_level = \
    srslte::log::get_level_from_string(std::move(ric_level_copy)); // needs checking
//  log.ric.set_level(log.ric_level); // needs checking
//  log.ric.set_hex_limit(args.ric_agent.log_hex_limit); // needs checking
  

// needs checking. 
//  log.e2ap.set_level(log.e2ap_level);
//  log.e2ap.set_hex_limit(args.ric_agent.log_hex_limit);
  

// needs checking
//  log.e2sm.init("E2SM",logger);
//  log.e2sm.set_level(log.e2sm_level);
//  log.e2sm.set_hex_limit(args.ric_agent.log_hex_limit);



  if (args.ric_agent.disabled) {
    set_state(RIC_DISABLED);
    return SRSRAN_SUCCESS;
  }

  /* Handle disabled functions. */
  if (!args.ric_agent.functions_disabled.empty()) {
    int i = 0,spos = -1,sslen = 0;
    int len = (int)args.ric_agent.functions_disabled.size();
    for (int i = 0; i < len ; ++i) {
      if (spos < 0
	  && (args.ric_agent.functions_disabled[i] == ','
	      || args.ric_agent.functions_disabled[i] == ' '
	      || args.ric_agent.functions_disabled[i] == '\t'))
	continue;
      else if (spos < 0) {
	spos = i;
	continue;
      }
      if (args.ric_agent.functions_disabled[i] == ',' || (i + 1) == len) {
	sslen = i - spos;
	if ((i + 1) == len && !(args.ric_agent.functions_disabled[i] == ','))
	  ++sslen;
	std::string ds = \
	  args.ric_agent.functions_disabled.substr(spos,sslen);
	functions_disabled.push_back(ds);
	RIC_DEBUG("disabled function: %s\n",ds.c_str());
	spos = -1;
      }
    }
  }

  /* Add E2SM service models. */
#ifdef ENABLE_RIC_AGENT_KPM
  model = new kpm_model(this);
  if (model->init()) {
    RIC_ERROR("failed to add E2SM-KPM model; aborting!\n");
    delete model;
    return SRSRAN_ERROR;
  }
  service_models.push_back(model);
  RIC_INFO("added model %s\n",model->name.c_str());
#endif

#ifdef ENABLE_SLICER
  model = new nexran_model(this);
  if (model->init()) {
    RIC_ERROR("failed to add E2SM-NEXRAN model; aborting!\n");
    delete model;
    return SRSRAN_ERROR;
  }
  service_models.push_back(model);
  RIC_INFO("added model %s\n",model->name.c_str());
#endif

  model = new gnb_nrt_model(this);
  if (model->init()) {
    RIC_ERROR("failed to add E2SM-gNB-NRT model; aborting!\n");
    delete model;
    return SRSRAN_ERROR;
  }
  service_models.push_back(model);
  RIC_INFO("added model %s\n",model->name.c_str());

  /* Construct a simple function_id->function lookup table. */
  for (it = service_models.begin(); it != service_models.end(); ++it) {
    for (it2 = (*it)->functions.begin(); it2 != (*it)->functions.end(); ++it2) {
      func = *it2;
      if (!(func->enabled)) {
	RIC_DEBUG("model %s function %s not enabled; not registering\n",
		  (*it)->name.c_str(),func->name.c_str());
	continue;
      }
      if (!is_function_enabled(func->name)) {
	RIC_DEBUG("model %s function %s administratively disabled; not registering\n",
		  (*it)->name.c_str(),func->name.c_str());
	func->enabled = false;
        continue;
      }
      function_id_map.insert(std::make_pair(func->function_id,func));
      RIC_DEBUG("model %s function %s (function_id %ld) enabled and registered\n",
		(*it)->name.c_str(),func->name.c_str(),func->function_id);

    }
  }

  set_state(RIC_INITIALIZED);

  /* Start up our recv socket thread and agent thread. */
  rx_sockets.reset(new srsran::socket_manager()); // renamed to socket_manager. Name argument RICSOCKET removed. Check passing logmap

  /* Enqueue a connect task for our thread.  This will run due to start() below. */
  agent_queue.push([this]() { connect(); }); // passing as a single argument. removing agent_queue_id

  /* Use the default high-priority level, below UDH, same as enb. */
  agent_thread_started = true;
  start(-1);

  return SRSRAN_SUCCESS;
}

#ifdef ENABLE_SLICER
void agent::test_slicer_interface()
{
  srsran::console("[agent] testing slicer interface...\n");
  std::vector<std::string> slice_names;

  srsran::console("[agent] configuring slices...\n");
  std::vector<slicer::slice_config_t> s_configs;
  for (auto it = slicer_test::slices.begin(); it != slicer_test::slices.end(); ++it) {
    slicer_test::print_slice(*it);
    s_configs.push_back(it->config);
  }
  enb_slicer_interface->slice_config(s_configs);

  srsran::console("[agent] checking all single slice status'...\n");
  std::vector<slicer::slice_status_t> s_status = enb_slicer_interface->slice_status({});
  for (auto it = s_status.begin(); it != s_status.end(); ++it) {
    slicer_test::print_slice_status(*it);
  }

  auto slice_name = slicer_test::slices[0].config.name;
  srsran::console("[agent] checking slice status for slice %s...\n", slice_name.c_str());
  s_status = enb_slicer_interface->slice_status({slice_name});
  for (auto it = s_status.begin(); it != s_status.end(); ++it) {
    slicer_test::print_slice_status(*it);
  }

  for (auto it = slicer_test::slices.begin(); it != slicer_test::slices.end(); ++it) {
    srsran::console("[agent] binding UEs for slice %s...\n", it->config.name.c_str());
    enb_slicer_interface->slice_ue_bind(it->config.name, it->imsi_list);
  }

  srsran::console("[agent] checking all slice status' after binding UEs...\n");
  s_status = enb_slicer_interface->slice_status({});
  for (auto it = s_status.begin(); it != s_status.end(); ++it) {
    slicer_test::print_slice_status(*it);
  }

  for (auto it = slicer_test::imsis_to_unbind.begin(); it != slicer_test::imsis_to_unbind.end(); ++it) {
    srsran::console("[agent] unbinding these UEs for slice %s ", it->name.c_str());
    slicer_test::print_imsis(it->imsi_list);
    enb_slicer_interface->slice_ue_unbind(it->name, it->imsi_list);
  }

  srsran::console("[agent] checking all slice status' after unbinding UEs...\n");
  s_status = enb_slicer_interface->slice_status({});
  for (auto it = s_status.begin(); it != s_status.end(); ++it) {
    slicer_test::print_slice_status(*it);
  }

  srsran::console("[agent] deleting slices ");
  for (auto it = slicer_test::slices_to_delete.begin(); it != slicer_test::slices_to_delete.end(); ++it) {
    srsran::console("%s ", (*it).c_str());
  }
  srsran::console("\n");
  enb_slicer_interface->slice_delete(slicer_test::slices_to_delete);

  srsran::console("[agent] checking all slice status' after unbinding UEs...\n");
  s_status = enb_slicer_interface->slice_status({});
  for (auto it = s_status.begin(); it != s_status.end(); ++it) {
    slicer_test::print_slice_status(*it);
  }
}
#endif

void agent::run_thread()
{
  while (agent_thread_started) {
    srsran::move_task_t task{};
    if (pending_tasks.wait_pop(&task) == true) // changed from int to boolean
      task();
  }
  RIC_INFO("exiting agent thread\n");
}

bool agent::is_function_enabled(std::string &function_name)
{
  std::list<std::string>::iterator it; 

  for (it = functions_disabled.begin(); it != functions_disabled.end(); ++it) {
    if (function_name.compare(*it) == 0)
      return false;
  }

  return true;
}

void agent::set_ric_id(uint32_t id,uint16_t mcc,uint16_t mnc)
{
  ric_id = id;
  ric_mcc = mcc;
  ric_mnc = mnc;
}

ric::ran_function_t *agent::lookup_ran_function(
  ran_function_id_t function_id)
{
  if (function_id_map.find(function_id) == function_id_map.end())
    return nullptr;
  else
    return function_id_map[function_id];
}

ric::subscription_t *agent::lookup_subscription(
  long request_id,long instance_id,ric::ran_function_id_t function_id)
{
  ric::subscription_t *sub;
  std::list<ric::subscription_t *>::iterator it; 

  for (it = subscriptions.begin(); it != subscriptions.end(); ++it) {
    sub = *it;
    if (sub->request_id == request_id
	&& sub->instance_id == instance_id
	&& sub->function_id == function_id)
      return sub;
  }

  return nullptr;
}

/**
 * Handle an error or closure of the RIC socket connection.  The goal
 * here was to allow users to specify that the agent shouldn't always,
 * infinitely attempt to reconnect, and should actually stop both its rx
 * and agent threads here, but that isn't supported by srsenb.
 *
 * (We cannot call stop() from within our rx thread nor our agent
 * thread: if the former, we deadlock on cleanup within the rx thread;
 * if the latter, we try to pthread_join ourself from ourself, after
 * adding a stop_impl task for ourself :).  What we need to implement
 * this is help from the enb stack itself (e.g. a daemon thread that
 * just waits for component threads to exit and joins them), but it
 * doesn't have any support to do this, presumably because none of its
 * radio threads would ever exit without taking the whole enb with it;
 * and because none of the upper layers should ever not reconnect.  So
 * we just stop reconnection attempts, and let our threads sleep forever
 * (until the enb main actually does stop them at enb termination).)
 */
void agent::handle_connection_error()
{
  if (args.ric_agent.no_reconnect) {
    RIC_INFO("disabling further RIC reconnects\n");
    /* stop(); */
    set_state(RIC_DISABLED);
    agent_queue.push([this]() { // Removing argument agent_queue_id
      disconnect();
    });
  }
  else {
    RIC_INFO("resetting agent connection (reconnect enabled)\n");
    RIC_INFO("pushing connection_reset (%lu)\n",agent_queue.size()); // no argument required here. Removing agent_queue_id
    agent_queue.push([this]() { // Removing argument agent_queue_id
      connection_reset();
    });
    RIC_INFO("pushed connection_reset (%lu)\n",agent_queue.size()); // no argument required here. Removing agent_queue_id. size does not take input
  }
}

int agent::connect()
{
  int ret;
  uint8_t *buf = NULL;
  ssize_t len;

  if (state == RIC_DISABLED || state == RIC_UNINITIALIZED)
    return SRSRAN_SUCCESS;
  else if (state == RIC_CONNECTED || state == RIC_ESTABLISHED)
    return SRSRAN_ERROR;

  /* Open a connection to the RIC. */
  if (ric_socket.is_open()) // is_init() changed to is_open
      ric_socket.close();
  if (!ric_socket.open_socket(srsran::net_utils::addr_family::ipv4,
			      srsran::net_utils::socket_type::stream,
  #if defined(USE_TCP)
                              srsran::net_utils::protocol_type::TCP)) {
    RIC_ERROR("failed to open a TCP socket to RIC; stopping agent\n");
  #else
			      srsran::net_utils::protocol_type::SCTP)) {
    RIC_ERROR("failed to open an SCTP socket to RIC; stopping agent\n");
  #endif
    /* Cannot recover from this error, so stop the agent. */
    stop();
    set_state(RIC_DISABLED);
    return SRSRAN_ERROR;
  }


  if (strlen(args.ric_agent.local_ipv4_addr.c_str()) > 0
      || args.ric_agent.local_port) {
    if (!ric_socket.bind_addr(args.ric_agent.local_ipv4_addr.c_str(),
			      args.ric_agent.local_port)) {
      RIC_ERROR("failed to bind local sctp address/port (%s,%d)\n",
		args.ric_agent.local_ipv4_addr.c_str(),
		args.ric_agent.local_port);
      stop();
      set_state(RIC_DISABLED);
      return SRSRAN_ERROR;
    }
  }

  // initmsg is not necessary for TCP, the other setsockopts are though
  /* Set specific stream options for this socket. */
  struct sctp_initmsg initmsg = { 1,1,3,5 };
  if (setsockopt(ric_socket.fd(),IPPROTO_SCTP,SCTP_INITMSG,
		 &initmsg,sizeof(initmsg)) < 0) {
    RIC_ERROR("failed to set sctp socket stream options (%s); stopping agent\n",
	      strerror(errno));
    ric_socket.close(); // ric_socket.reset() is now ric_socket.close()
    /* Cannot recover from this error, so stop the agent. */
    stop();
    set_state(RIC_DISABLED);
    return SRSRAN_ERROR;
  }
  int reuse = 1;
  if (setsockopt(ric_socket.fd(),SOL_SOCKET,SO_REUSEADDR,
		 &reuse,sizeof(reuse)) < 0) {
    RIC_WARN("failed to set sctp socket reuseaddr: %s\n",strerror(errno));
  }

  if (!ric_socket.connect_to(args.ric_agent.remote_ipv4_addr.c_str(),
				args.ric_agent.remote_port,
				&ric_sockaddr)) {
    RIC_ERROR("failed to connect to %s",
	      args.ric_agent.remote_ipv4_addr.c_str());
    ric_socket.close(); // ric_socket.reset() is now ric_socket.close()
    /* Might be recoverable; don't stop the agent. */
    handle_connection_error();
    return SRSRAN_ERROR;
  }

  /* Add an rx handler for the RIC socket. */
  auto ric_socket_handler =
    [this](srsran::unique_byte_buffer_t pdu,
	   const sockaddr_in& from,const sctp_sndrcvinfo& sri,int flags) {
      handle_message(std::move(pdu),from,sri,flags);
      //handle_message(pdu,from,sri,flags);
  };
  rx_sockets->add_socket_handler(ric_socket.fd(),srsran::make_sctp_sdu_handler(ric, agent_queue, ric_socket_handler)); // add_socket_sctp_pdu_handler renamed to add_socket_handler
  // for TCP just use make_sdu_handler


  set_state(RIC_CONNECTED);
  RIC_INFO("connected to RIC on %s",
	   args.ric_agent.remote_ipv4_addr.c_str());

  #if !defined(E2_LIKE)
  /* Send an E2Setup request to RIC. */
  ret = ric::e2ap::generate_e2_setup_request(this,&buf,&len);
  if (ret) {
    RIC_ERROR("failed to generate E2setupRequest; disabling RIC agent!\n");
    stop();
    set_state(RIC_DISABLED);
    if (buf)
      free(buf);
    return 1;
  }
  if (!send_sctp_data(buf,len)) {
    RIC_ERROR("failed to send E2setupRequest; aborting connect\n");
    if (buf)
      free(buf);
    handle_connection_error();
    return 1;
  }
  RIC_INFO("sent E2setupRequest to RIC\n");
  free(buf);

  /*
   * Wait for E2setupResponse or Failure.  For now, it's ok to busy-wait
   * in this thread since it's dedicated to the connection.  Later, we
   * need to be more careful.
   */
  while (state == RIC_CONNECTED && !is_state_stale(60)) {
    RIC_DEBUG("waiting for E2setupResponse...\n");
    sleep(5);
  }
  
  /*if (state != RIC_ESTABLISHED) {
    RIC_ERROR("did not receive successful E2setupResponse; aborting connect\n");
    set_state(RIC_FAILURE);
    handle_connection_error();
    return 1;
  }*/
  #else

  RIC_INFO("E2-like interface enabled, skipping setup request\n");
  set_state(RIC_ESTABLISHED);

  #endif

  return SRSRAN_SUCCESS;
}

bool agent::handle_message(srsran::unique_byte_buffer_t pdu,
			   const sockaddr_in &from,const sctp_sndrcvinfo &sri,
			   int flags)
{
  //printf("GOT TO HANDLE_MESSAGE\n");
  int ret;

  /* If this "message" is an SCTP notification/event, handle it. */
  if (flags & MSG_NOTIFICATION) {
    union sctp_notification *n = (union sctp_notification *)pdu->msg;
    switch (n->sn_header.sn_type) {
    case SCTP_SHUTDOWN_EVENT:
      struct sctp_shutdown_event *shut; 
      shut = (struct sctp_shutdown_event *)pdu->msg; 
      RIC_DEBUG("recv SCTP_SHUTDOWN (assoc %d)\n",shut->sse_assoc_id);
      handle_connection_error();
      break;
    default:
      RIC_DEBUG("received sctp event %d; ignoring\n",n->sn_header.sn_type);
      break;
    }
    //printf("Finished handling MSG_NOTIFICATION\n");
    return true;
  }
  //printf("Past flags check\n");

  #if defined(E2_LIKE)
  
  // agent_cmd.bin handled in txrx.cc to control PHY layer
  if (pdu->N_bytes > 0) {
    RIC_INFO("received e2-lite message: %.*s\n", pdu->N_bytes, pdu->msg);
    printf("received N_bytes=%d, e2-lite message: %.*s\n", pdu->N_bytes, pdu->N_bytes, pdu->msg);

    // Determine the file to write based on message
    std::string target_path;
    if (pdu->N_bytes == 1) {
      target_path = agent_command_path;  // For single-byte commands (k/i)
    } else if (pdu->N_bytes == 8) {
      target_path = agent_prb_path;      // For 8-byte PRB information
    } else {
      RIC_WARN("Unexpected message size: %d bytes\n", pdu->N_bytes);
      return false;
    }
    FILE* f_o = fopen(target_path.c_str(), "wb");
    if (f_o){
      RIC_INFO("Opened %s successfully", target_path.c_str());
      printf("Opened %s successfully\n", target_path.c_str());
      size_t written = fwrite(pdu->msg, 1, pdu->N_bytes, f_o);
      fclose(f_o);
      if (written != pdu->N_bytes) {
        RIC_ERROR("Failed to write complete message to %s\n", target_path.c_str());
        return false;
      }
      RIC_INFO("wrote e2-lite message to %s\n", target_path.c_str()); 
      printf("wrote e2-lite message to %s\n", target_path.c_str()); 
    }else if (!f_o){
      RIC_ERROR("Failed to open %s\n", target_path.c_str());
      perror("fopen error");
      return false;
    }
  }
  
  auto time = std::chrono::system_clock::now().time_since_epoch();
  std::chrono::seconds seconds = std::chrono::duration_cast< std::chrono::seconds >(time);
  std::chrono::milliseconds ms = std::chrono::duration_cast< std::chrono::milliseconds >(time);
  RIC_INFO("Timestamp: %0.7f\n", (double) seconds.count() + ((double) (ms.count() % 1000)/1000.0));
  // printf("Timestamp: %0.7f\n", (double) seconds.count() + ((double) (ms.count() % 1000)/1000.0));


  // Handle message processing
const char *msg = NULL;
if (pdu->N_bytes >= 1) {
    msg = (const char *)pdu->msg;
    printf("Message gotten from RIC is %.*s\n", pdu->N_bytes, msg);
}

// Always send KPMs for either 'k' command OR 8-byte message
if ((pdu->N_bytes == 1 && msg && msg[0] == 'k') || pdu->N_bytes == 8) {
  printf("Filling up KPMs to send to RAN\n");
  fill_class_metrics();
}

// Always process I/Q samples for either 'i' command or 8-byte message
if (pdu->N_bytes == 1 && msg != NULL && msg[0] == 'i') {
    printf("Filling up I/Q samples to send to RAN\n");
    FILE* f = fopen(save_path.c_str(), "rb");
    if (f) {
        fseek(f, 0, SEEK_END);
        fseek(f, -614400, SEEK_CUR);
        size_t read = fread(iq_buffer, 1, 614400, f);
        fclose(f);
        
        if (read == 614400) {
            RIC_INFO("IQ data available to be read\n");
            std::cout << "IQ data available to be read" << std::endl;
        } else {
            RIC_WARN("Failed to get total read chunk (%lu != 614400)\n", read);
            memset(iq_buffer, 0, 614400);
        }
    } else {
        memset(iq_buffer, 0, 614400);
    }

    uint8_t* buf = iq_buffer;
    for (int i = 0; i < 614400; i += 10000) {
        int size = (614400 - i > 10000) ? 10000 : 614400 - i;
        send_sctp_data(buf, size);
        buf += size;
    }
    printf("Sent IQ samples to RIC\n");
    RIC_INFO("Sent IQ samples to RIC");
}

return true;

  #else

  /* Otherwise, handle the message. */
  ret = ric::e2ap::handle_message(this,0,pdu->msg,pdu->N_bytes);
  if (ret == SRSRAN_SUCCESS)
    return true;
  else {
    RIC_ERROR("failed to handle incoming message (%d)\n",ret);
    return false;
  }

  #endif
}

bool agent::send_sctp_data(uint8_t *buf,ssize_t len)
{
  ssize_t ret;

  ret = sctp_sendmsg(ric_socket.fd(),(const void *)buf,len,
		     (struct sockaddr *)&ric_sockaddr,sizeof(ric_sockaddr),
		     htonl(E2AP_SCTP_PPID),0,0,0,0);
  if (ret == -1) {
    RIC_ERROR("failed to send %ld bytes\n",len);
    printf("failed to send %ld bytes\n",len);
    return false;
  }

  return true;
}

void agent::disconnect(bool use_shutdown)
{
  if (!(state == RIC_CONNECTED || state == RIC_ESTABLISHED))
    return;

  RIC_INFO("disconnecting from RIC\n");
  if (use_shutdown) {
      struct sctp_sndrcvinfo sri = { 0 };
      sri.sinfo_flags = SCTP_EOF;
      sctp_send(ric_socket.fd(),NULL,0,&sri,0);
  }
  rx_sockets->remove_socket(ric_socket.fd());
  ric_socket.close(); // change from reset() to close ()

  ric_mcc = ric_mnc = 0;
  ric_id = 0;

  set_state(RIC_DISCONNECTED);
}

void agent::stop()
{
  if (state == RIC_DISABLED || state == RIC_UNINITIALIZED)
    return;

  agent_queue.push([this]() { stop_impl(); }); // remove agent_queue_id arg.
  wait_thread_finish();
}

void agent::stop_impl()
{
  RIC_INFO("stopping agent\n");

  disconnect();
  rx_sockets->stop();
  agent_queue.empty(); // erase_queue(agent_queue_id) renamed to empty
  agent_queue = pending_tasks.add_queue();
  set_state(RIC_INITIALIZED);
  agent_thread_started = false;
}

/**
 * Implements an E2 reset.  Must not schedule any tasks, since it might
 * be called from connection_reset(), which clears the task queue.
 */
int agent::reset()
{
  RIC_INFO("resetting E2 agent state\n");

  /* TODO: cancel subscription actions/timers in a meaningful way. */
  subscriptions.clear();

  return SRSRAN_SUCCESS;
}

static const char *state_to_string(agent_state_t state)
{
    switch (state) {
    case RIC_UNINITIALIZED:
	return "INITIALIZED";
    case RIC_CONNECTED:
	return "CONNECTED";
    case RIC_ESTABLISHED:
	return "ESTABLISHED";
    case RIC_FAILURE:
	return "FAILURE";
    case RIC_DISCONNECTED:
	return "DISCONNECTED";
    case RIC_DISABLED:
	return "DISABLED";
    default:
	return "INVALID";
    }
}

void agent::set_state(agent_state_t state_)
{
    state = state_;
    if (state == RIC_ESTABLISHED) {
	/* We have a successful connection, so clear our current delay. */
	current_reconnect_delay = 0;
    }
    state_time = std::time(NULL);
    RIC_DEBUG("RIC state -> %s\n",state_to_string(state_));
}

bool agent::is_state_stale(int seconds)
{
    if ((std::time(NULL) - state_time) >= seconds)
	return true;
    return false;
}

/**
 * Implements a connection reset: disconnect(), reset(), connect().
 */
int agent::connection_reset(int delay)
{
  RIC_INFO("resetting agent connection\n");

  if (delay < 0) {
    delay = current_reconnect_delay;
    /* Update our current reconnect delay. */
    current_reconnect_delay += RIC_AGENT_RECONNECT_DELAY_INC;
    if (current_reconnect_delay > RIC_AGENT_RECONNECT_DELAY_MAX)
      current_reconnect_delay = RIC_AGENT_RECONNECT_DELAY_MAX;
  }

  reset();
  disconnect();
  agent_queue.empty(); // change from erase_queue(agent_queue_id) to empty()
  agent_queue = pending_tasks.add_queue();
  set_state(RIC_INITIALIZED);
  /* This is only "safe" because the agent_queue was just cleared. */
  RIC_INFO("delaying new connection for %d seconds",delay);
  sleep(delay);
  return connect();
}

/*
 * Fill up metrics structure
 */
void agent::fill_class_metrics() {
  printf("Started metrics collection..\n");
  // Instantiate a struct for all metrics collected
  classification_metrics_t metrics = {};
  auto time = std::chrono::system_clock::now().time_since_epoch();
  std::chrono::seconds seconds = std::chrono::duration_cast< std::chrono::seconds >(time);
  std::chrono::milliseconds ms = std::chrono::duration_cast< std::chrono::milliseconds >(time);
  
  // // First, lets handle scheduler metrics gotten from the sched_time_pf.cc 
  // // This starts working only when ue is connected!!
  // // printf("\tFilling scheduler metrics..\n");
  // // printf("\tFile to open: %s\n", sched_save_path.c_str());
  // FILE* sched_in = fopen(sched_save_path.c_str(), "r");
  // if(sched_in == NULL) {
  //   printf("Failed to open scheduler metrics file!\n");
  //   perror("");
  //   RIC_ERROR("Failed to open scheduler metrics file!");
  //   return;
  // }
  // fseek(sched_in, 0L, SEEK_END);
  // size_t sz = ftell(sched_in);
  
  // // printf("%lu / %lu\n", sz, sizeof(sched_metrics_t));
  // size_t total_entries = sz / sizeof(sched_metrics_t);
  // fseek(sched_in, 0, SEEK_SET);

  // std::vector<sched_metrics_t> *sched_metrics = new std::vector<sched_metrics_t>();
  // // printf("Allocated vector of size %lu\n", total_entries);
  // //sched_metrics->reserve(total_entries);

  // for(size_t i = 0; i < total_entries; i++) {
  //   sched_metrics_t t = {};
  //   size_t read_bytes = fread((char*)&t, 1, sizeof(sched_metrics_t), sched_in);
  //   if(read_bytes != sizeof(sched_metrics_t)) {
  //     printf("Failed to read the data we needed!\n");
  //     return;
  //   }
  //   sched_metrics->push_back(t);
  // }
  // // delete file
  // FILE* _i_dont_care = freopen(nullptr, "w", sched_in);
  // fclose(sched_in);
  // // RIC_INFO("Removed scheduler file...");
  // // printf("Removed scheduler file...");


  // Now we would start filling up the struct with some of the public metrics.
  // fill timestamp,enbid and initialize the number of prbs to zero
  // printf("Started getting enbid, time stamp and initialized available prbs \n");
  metrics.timestamp = (double) seconds.count() + ((double) (ms.count() % 1000)/1000.0);
  metrics.base_station_id = enb_id;
  // metrics.available_prbs = 0;
  printf("Timestamp %f,enbid %u \n",metrics.timestamp,  metrics.base_station_id);

  // get major metrics from RAN. Create a metrics struct to fill
  //printf("Fetching metrics from RAN enb_metrics_interface..\n");
  srsenb::enb_metrics_t enb_metrics = {}; //(Isnt this meant to be a pointer??)

  // causes issues? 
  if(enb_metrics_interface->get_metrics(&enb_metrics)) {
    RIC_INFO("Got eNB metrics!");
    printf("Got eNB metrics!\n");
  } else if(!enb_metrics_interface->get_metrics(&enb_metrics)) {
    RIC_ERROR("Failed to get eNB metrics!");
    printf("Failed to get eNB metrics!\n");
  }

  // initialize a vector for us to use to get ue specific metrics
  metrics.ue_metrics = new std::vector<classification_ue_metrics_t>();

  // int avg_available_prbs = 0;
  // uint64_t current_ul_mask = 0;

  // get all UE metrics for every UE in PHY_METRICS
  // printf("Beginning loop..\n");
  // printf("Total number of PHY metric entries: %lu\n", enb_metrics.phy.size());
  // printf("Total number of MAC metric entries: %lu\n", enb_metrics.stack.mac.ues.size());
  for(auto& phy_metric : enb_metrics.phy) {
    classification_ue_metrics_t tmp_metrics = {};

    // fill in what we can right now...
    tmp_metrics.c_rnti        = phy_metric.rnti;
    tmp_metrics.pusch_sinr    = std::max(0.1f, phy_metric.ul.pusch_sinr);
    tmp_metrics.pucch_sinr    = std::max(0.1f, phy_metric.ul.pucch_sinr);
    tmp_metrics.rssi          = phy_metric.ul.rssi;
    tmp_metrics.turbo_iters   = phy_metric.ul.turbo_iters;
    tmp_metrics.ul_mcs        = std::max(0.1f, phy_metric.ul.mcs);
    tmp_metrics.ul_n_samples  = phy_metric.ul.n_samples;
    tmp_metrics.dl_mcs        = std::max(0.1f, phy_metric.dl.mcs);
    tmp_metrics.dl_n_samples  = phy_metric.dl.n_samples;
    
    printf("These are the phy metrics, rnti: %u, PUSCH_SINR: %f\n", tmp_metrics.c_rnti, tmp_metrics.pusch_sinr);
    printf("These are the phy metrics, PUCCH SINR: %f\n", tmp_metrics.pucch_sinr);
    printf("These are the phy metrics, RSSI: %f\n", tmp_metrics.rssi);
    printf("These are the phy metrics, TURBO ITERS: %f\n", tmp_metrics.turbo_iters);
    printf("These are the phy metrics, UL MCS: %f\n", tmp_metrics.ul_mcs);
    printf("These are the phy metrics, UL # Samples: %d\n", tmp_metrics.ul_n_samples);
    printf("These are the phy metrics, DL MCS: %f\n", tmp_metrics.dl_mcs);
    printf("These are the phy metrics, DL # samples: %d\n", tmp_metrics.dl_n_samples);
    // find and fill the MAC metrics
    uint16_t nof_tti = 0;
    // save the # ttis in case we need them for SCHED metrics
        
    // found the right one, populate what we need

    for (uint32_t j = 0; j < enb_metrics.stack.mac.ues.size(); j++) {
      srsenb::mac_ue_metrics_t mac_metric = enb_metrics.stack.mac.ues[j];
      // srsenb::mac_ue_metrics_t rlc_metric = enb_metrics.stack.rlc.ues[j].bearer;
    //for (auto& mac_metric : enb_metrics.stack.mac.ues) {
      if (mac_metric.rnti == tmp_metrics.c_rnti) {
        nof_tti                 = mac_metric.nof_tti;
        tmp_metrics.tx_pkts     = mac_metric.tx_pkts;
        tmp_metrics.tx_errors   = mac_metric.tx_errors;
        tmp_metrics.tx_brate    = std::max(0.1f, (mac_metric.tx_brate / (nof_tti * 0.001f)));
        // tmp_metrics.tx_brate    = mac_metric.tx_brate;
        int guard_tx_pkts       = std::max(1, tmp_metrics.tx_pkts);
        tmp_metrics.tx_bler     = 100 * tmp_metrics.tx_errors / guard_tx_pkts;//tmp_metrics.tx_pkts;
        tmp_metrics.rx_pkts     = mac_metric.rx_pkts;
        tmp_metrics.rx_errors   = mac_metric.rx_errors;
        int guard_rx_pkts       = std::max(1, tmp_metrics.rx_pkts);
        tmp_metrics.rx_bler     = 100 * tmp_metrics.rx_errors / guard_rx_pkts; //tmp_metrics.rx_pkts;
        tmp_metrics.rx_brate    = std::max(0.1f, (float) mac_metric.rx_brate / (nof_tti * 0.001f));
        tmp_metrics.ul_buffer   = mac_metric.ul_buffer;
        tmp_metrics.dl_buffer   = mac_metric.dl_buffer;
        tmp_metrics.dl_cqi      = std::max(0.1f, mac_metric.dl_cqi);

        printf("\tMAC metrics, nof tti: %u\n", nof_tti);
        printf("\tMAC metrics, tx packets: %d\n", tmp_metrics.tx_pkts);
        printf("\tMAC metrics, tx errors: %d\n", tmp_metrics.tx_errors);
        printf("\tMAC metrics, tx bytes: %d\n", mac_metric.tx_brate);
        printf("\tMAC metrics, tx bitrate: %d\n", tmp_metrics.tx_brate);
        printf("\tMAC metrics, tx block error: %d\n", tmp_metrics.tx_bler);
        printf("\tMAC metrics, rx packets: %d\n", tmp_metrics.rx_pkts);
        printf("\tMAC metrics, rx errors: %d\n", tmp_metrics.rx_errors);
        printf("\tMAC metrics, rx bytes: %d\n", mac_metric.rx_brate);
        printf("\tMAC metrics, rx bitrate: %d\n", tmp_metrics.rx_brate);
        printf("\tMAC metrics, rx block error: %d\n", tmp_metrics.rx_bler);
        printf("\tMAC metrics, ul buffer: %d\n", tmp_metrics.ul_buffer);
        printf("\tMAC metrics, dl buffer: %d\n", tmp_metrics.dl_buffer);
        printf("\tMAC metrics, dl cqi: %f\n", tmp_metrics.dl_cqi);

        // printf("\tMAC metrics, nof tti: %u\n", nof_tti);
        // printf("\tMAC metrics, tx packets: %d\n", mac_metric.tx_pkts);
        // printf("\tMAC metrics, tx errors: %d\n", mac_metric.tx_errors);
        // printf("\tMAC metrics, tx bytes: %d\n", mac_metric.tx_brate);
        // printf("\tMAC metrics, tx bitrate: %d\n", mac_metric.tx_brate);
        // printf("\tMAC metrics, rx packets: %d\n", mac_metric.rx_pkts);
        // printf("\tMAC metrics, rx errors: %d\n", mac_metric.rx_errors);
        // printf("\tMAC metrics, rx bytes: %d\n", mac_metric.rx_brate);
        // printf("\tMAC metrics, rx bitrate: %d\n", mac_metric.rx_brate);
        // printf("\tMAC metrics, ul buffer: %d\n", mac_metric.ul_buffer);
        // printf("\tMAC metrics, dl buffer: %d\n", mac_metric.dl_buffer);
        // printf("\tMAC metrics, dl cqi: %f\n", mac_metric.dl_cqi);


        // break;
      }
    }

    

        

    
    // prepare some temporary variables
    // avg_available_prbs = 0;
    // uint32_t avg_pending_data = 0;
    // uint32_t avg_required_prbs = 0;
    // size_t granted_prbs = 0;
    // size_t counter = 0;

    // find, process, and fill all SCHED metrics
    // for (auto sched_m = sched_metrics->begin(); sched_m != sched_metrics->end(); sched_m++) {
    //   if(sched_m->ue_rnti == tmp_metrics.c_rnti) {
    //     // found the right one, process what we need
    //     avg_available_prbs += sched_m->available_prbs;
    //     avg_pending_data += sched_m->pending_data;
    //     avg_required_prbs += sched_m->required_prbs;
    //     granted_prbs = sched_m->granted_prbs;
    //     current_ul_mask = sched_m->current_ul_mask;
    //     counter++;
    //   }
    // }

    // // process them
    // avg_available_prbs  /= std::max((size_t)1, counter);
    // avg_pending_data    /= std::max((size_t)1, counter);
    // avg_required_prbs   /= std::max((size_t)1, counter);
    
    // // save them
    // tmp_metrics.pending_data  = avg_pending_data;
    // tmp_metrics.required_prbs = avg_required_prbs;
    // tmp_metrics.granted_prbs  = granted_prbs;
    
    // printf("Here are the sched_metrics for %hu\n", tmp_metrics.c_rnti);
    // printf("\tAverage pending data: %u\n", tmp_metrics.pending_data);
    // printf("\tRequired PRBs: %u\n", tmp_metrics.required_prbs);
    // printf("\tGranted PRBs : %lu\n", tmp_metrics.granted_prbs);
        

    // push it to the back of the 
    metrics.ue_metrics->push_back(tmp_metrics);
  }

  // printf("Loop complete..\n");
  // printf("\tAverage available PRBs: %d\n", avg_available_prbs);
    
  // metrics.available_prbs = avg_available_prbs;


  // // serialize the metrics
  uint8_t* serialized_data = nullptr;

  size_t num_bytes = serialize_classification_metrics(&serialized_data, metrics);

  if(serialized_data == nullptr) {
    RIC_ERROR("FAILED TO SERIALIZE METRICS!!!");
  } else {
    // send the metrics 
    printf("Sending serialized data with size %lu\n", num_bytes);
    send_sctp_data(serialized_data, num_bytes);
    //printf("Done sending data\n");

    free(serialized_data);

  }
 
  
}

/*
  Serializes a `classification_metrics_t` structure into a series of bytes to be
  sent over the network. Returns the length of the data to be sent, or 0 on 
  failure. If the function does not fail, `buffer needs to be freed in order to 
  prevent a memory leak
*/
size_t agent::serialize_classification_metrics(uint8_t** buffer, classification_metrics_t& metrics) {
  // calculate how much space we will need to reserve
  //  double + uint32_t + int + int + sizeof(ue_data)*num_ues
  size_t num_ues = metrics.ue_metrics->size();
  printf("Found total of %lu UEs connected\n", num_ues);
  size_t non_ue_bytes = sizeof(double) + sizeof(uint32_t);
  size_t total_bytes = non_ue_bytes + 
                       sizeof(size_t) +
                       sizeof(classification_ue_metrics_t)*num_ues;
  printf("size of classification metrics: %lu\n",sizeof(classification_ue_metrics_t));
  // allocate that memory
  //printf("Total bytes to allocate: %lu\n", total_bytes);
  *buffer = (uint8_t*)malloc(total_bytes);

  if(!*buffer) {
    perror("Malloc failed");
    return 0;
  }

  // copy the beginning of the metrics into the buffer
  memcpy(*buffer, &metrics, non_ue_bytes);

  // copy over the number of UEs that we have
  memcpy(*buffer+non_ue_bytes, &num_ues, sizeof(size_t));
  //printf("Non-UE bytes to be sent: %lu\n", non_ue_bytes + sizeof(size_t));
  //printf("UE data bytes to be sent: %lu\n", sizeof(classification_ue_metrics_t)*num_ues);

  // now iterate over each UE and save their data
  size_t counter_offset = non_ue_bytes + sizeof(size_t);
  for(auto ue_entry = metrics.ue_metrics->begin(); ue_entry != metrics.ue_metrics->end(); ue_entry++) {
    memcpy(*buffer+counter_offset, &(*ue_entry), sizeof(classification_ue_metrics_t));
    counter_offset += sizeof(classification_ue_metrics_t);
  }

  return total_bytes;
}



}
