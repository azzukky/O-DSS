/**
 * Copyright 2013-2021 Software Radio Systems Limited
 *
 * This file is part of srsRAN.
 *
 * srsRAN is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of
 * the License, or (at your option) any later version.
 *
 * srsRAN is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * A copy of the GNU Affero General Public License can be found in
 * the LICENSE file in the top-level directory of this distribution
 * and at http://www.gnu.org/licenses/.
 *
 */

#ifndef SRSENB_PHY_METRICS_H
#define SRSENB_PHY_METRICS_H

namespace srsenb {

// PHY metrics per user

struct ul_metrics_t {
  float n;
  float pusch_sinr;
  float pucch_sinr;
  float rssi;
  float turbo_iters;
  float mcs;
  int   n_samples;
  int   n_samples_pucch;
};

struct dl_metrics_t {
  float mcs;
  int   n_samples;
};

struct phy_metrics_t {
//Adding cell id parameter for KPI xApp metrics collection
#ifdef ENABLE_RIC_AGENT_KPM
  uint32_t cc_idx;
#endif

  uint16_t rnti; 

  dl_metrics_t dl;
  ul_metrics_t ul;
};

} // namespace srsenb

#endif // SRSENB_PHY_METRICS_H
