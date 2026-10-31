/* SPDX-License-Identifier: MIT */
#pragma once
#include "Sm8750GmuCommandDb.h"
#ifdef __cplusplus
extern "C" {
#endif
/* speed_bin is the observed 9-bit QFPROM value; soc_code is Qualcomm socinfo's
 * combined pcode/feature code. Policy order follows the original PKX110 DT. */
AdrenoHfiStartupStatus PaganiGpuBuildStartup(const Sm8750GmuVoteInputs *,
    uint32_t speed_bin,uint32_t soc_code,AdrenoHfiStartupConfig *,unsigned *initial,unsigned *bandwidth);
#ifdef __cplusplus
}
#endif
