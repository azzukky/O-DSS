# Our Changes
This file outlines the changes we have made to this particular srsRAN codebase 
for various different works. The changes are separated by project.

## AD Work
### Tasks
The main parts of this worked involved:

1. Collecting desired metrics
2. Modifying the scheduler to save particular key metrics to a file
3. Sending metrics to the IMI
4. Receiving signals from IMI to trigger an S1 Handover

### Files
#### `srsenb/src/ric/agent.cc`
* Modified `agent::handle_message`
* Added `agent::fill_class_metrics`
* Added `agent::serialize_classification_metrics`

#### `srsenb/hdr/ric/agent.h`
* Added `struct classification_ue_metrics_t`
* Added `struct classification_metrics_t`
* Added `struct sched_metrics_t`
* Added `std::string save_path`
* Added `std::string tmp_path`
* Added `std::string agent_command_path`
* Added `uint32_t enb_id`
* Added `std::string sched_save_path`
* Added `std::string rrc_command_path`

#### `srsenb/src/phy/lte/cc_worker.cc`
* Fixed order in RNTI assignment in `cc_worker::ue::metrics_read`

#### `srsenb/src/phy/lte/sf_worker.cc`
* Propagate rnti changes up thru `sf_worker::get_metrics`

#### `srsenb/src/phy/phy.cc`
* Propagate rnti changes up thru `phy::get_metrics`

#### `srsenb/src/stack/enb_stack_lte.cc`
* Added debug prints in `enb_stack_lte::get_metrics`

#### `srsenb/src/stack/mac/mac.cc`
* Removed call to `ric_comm` in `mac::get_dl_sched`
* Modified `ric_comm` to remove constant call to metrics functions that messed 
  up our collection

#### `srsenb/src/stack/mac/schedulers/sched_time_pf.cc`
* Modified `sched_time_pf::try_ul_alloc` to include the missing low-level 
  metrics that we needed (PRB info)

#### `srsenb/src/stack/rrc/rrc_mobility.cc`
* Added function `rrc::ue::rrc_mobility::handle_dummy_report` to initiate 
  handover procedures

#### `srsenb/src/stack/rrc/rrc_ue.cc`
* Added function `rrc::ue::start_custom_s1_handover` to tell the mobility 
  manager to start an S1 handover

#### `srsenb/src/stack/rrc/rrc.cc`
* Added function `rrc::start_custom_handover` to trigger S1 handover
* Modified `rrc::get_metrics` to trigger S1 handover if signal from IMI has been
  sent. **NEED TO CHANGE THIS AT SOME POINT, SHOULDN'T BE INCLUDED IN THE METRICS LOOP**
