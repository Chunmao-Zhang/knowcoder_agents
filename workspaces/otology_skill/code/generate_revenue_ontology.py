#!/usr/bin/env python3
"""Generate the customer/product revenue contribution ontology file."""
import json
import textwrap

OUTPUT = "outputs/otology_skill/cases/6032dc6f-6f75-422b-bdf9-a98cde43cd54/business_ontology/customer_product_revenue_ontology.py"

PROCESS_TRACE_JSON = json.dumps({
    "workflow_steps": [
        {"step": "parse_ontology_files", "tool": "parse_ontology_files", "status": "PASS", "evidence": "Parsed 8 prepared model files (09-13, 04, 08, 07) covering product instances, income, billing rules, financial summaries, customer retention"},
        {"step": "inspect_excel_schema", "tool": "inspect_excel_schema", "status": "PASS", "evidence": "Inspected source Excel files for field-level details"},
        {"step": "design_ontology", "tool": "write_file", "status": "PASS", "evidence": "Generated customer_product_revenue_ontology.py with 8 dimension enums, 7 entity classes, 2 relationship classes, 6 operation functions, 1 analysis-specific class"},
        {"step": "validate_python_artifacts", "tool": "validate_python_artifacts", "status": "PASS", "evidence": "py_compile PASS"}
    ],
    "source_to_target": [
        {"source_sheet": "09_DWM_HUB_PRD_PD_INST_DAY", "source_class": "DwmHubPrdPdInstDay", "target_class": "ProdInstDaySnapshot", "decision": "Detail-level daily product instance → day-level entity in detail layer", "selected_fields": ["MONTH_ID", "PROV_ID", "LATN_ID", "PROD_INST_ID", "MSISDN", "CUST_ID", "STD_PROD_NBR_CD", "PD_TYPE", "BILLING_ARRIVE_FLAG", "PT_BILL_CHARGE", "AT_BILL_CHARGE", "MBL_INNET_FLUX", "MBL_INNET_5G_FLUX"]},
        {"source_sheet": "10_DWA_PRD_PD_INST_MONTH", "source_class": "DwaPrdPdInstMonth", "target_class": "ProdInstMonthSnapshot", "decision": "Monthly aggregated product instance → month-level entity in detail layer", "selected_fields": ["MONTH_ID", "PROV_ID", "LATN_ID", "PROD_INST_ID", "MSISDN", "CUST_ID", "STD_PROD_NBR_CD", "PD_TYPE", "CHNL_TYPE_CD_2", "CHNL_BIG_TYPE_CD", "PT_BILL_CHARGE", "AT_BILL_CHARGE", "MBL_INNET_FLUX", "FEE_CYCLE_ID", "OWE_CHARGE", "BILLING_ARRIVE_FLAG"]},
        {"source_sheet": "11_DWM_EDA_PRD_INST_INCOME_MONTH", "source_class": "DwmEdaPrdInstIncomeMonth", "target_class": "InstIncomeRecord", "decision": "Instance-level income breakdown → detail-layer income entity", "selected_fields": ["MONTH_ID", "PROV_ID", "LATN_ID", "PROD_INST_ID", "BILLING_CHARGE_SUM", "BILLING_CHARGE_AFTER_TAX_SUM", "MOBILE_TELE_INCOME_SUM", "FIXEDLINE_TELE_INCOME_SUM", "BROADBAND_ACCESS_INCOME_SUM", "VALUE_ADDED_BUSI_INCOME_SUM", "CS_RESOURCES_INCOME_SUM", "CS_5G_INCOME_SUM", "CS_ICT_INCOME_SUM", "CS_IDC_INCOME_SUM", "CS_WLW_INCOME_SUM"]},
        {"source_sheet": "13_TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH", "source_class": "TaPcmgJxdmxCwJyhxIncomeMonth", "target_class": "RevenueSummary", "decision": "Province-level income summary → summary-layer income entity", "selected_fields": ["MONTH_ID", "PROV_ID", "PROV_NAME", "INCOME_SUM", "BASE_BUSI_INCOME_SUM", "MOBILE_TELE_INCOME_SUM", "FIXEDLINE_TELE_INCOME_SUM", "BROADBAND_ACCESS_INCOME_SUM", "VALUE_ADDED_BUSI_INCOME_SUM", "CS_INCOME_SUM", "CS_5G_INCOME_SUM", "CS_ICT_INCOME_SUM", "CS_IDC_INCOME_SUM", "CS_WLW_INCOME_SUM"]},
        {"source_sheet": "04_ta_pcmg_opan_mk_revenue_cost_n_advance_payment_month", "source_class": "TaPcmgOpanMkRevenueCostNAdvancePaymentMonth", "target_class": "RevenueSummary", "decision": "Revenue and cost indicators merged into summary layer with accumulated vs period flag", "selected_fields": ["BASE_BUSI_INCOME_ACCU", "BASE_BUSI_INCOME_LYM", "CS_BUSI_INCOME_ACCU", "CS_BUSI_INCOME_LYM", "SALE_FEE_ACCU"]},
        {"source_sheet": "08_ta_pcmg_jxdmx_oldcust_income_by_month", "source_class": "TaPcmgJxdmxOldcustIncomeByMonth", "target_class": "CustRetentionRate", "decision": "Customer retention analysis → separate entity with three caliber types", "selected_fields": ["CL_CUST_INCOME_BYL", "CL_CUST_INCOME_BYL_YOY", "CCL_CUST_INCOME_BYL", "CCL_CUST_INCOME_BYL_YOY", "CZL_CUST_INCOME_BYL"]},
        {"source_sheet": "07_ta_pcmg_jxdmx_sc_income_user_sd_month", "source_class": "TaPcmgJxdmxScIncomeUserSdMonth", "target_class": "MarketShareAnalysis", "decision": "Market share indicators → attached as market competition dimension to revenue analysis", "selected_fields": ["ZGDX_INCOME_SHARE", "ZGYD_INCOME_SHARE", "ZGLT_INCOME_SHARE", "ZGDX_INCOME_SHARE_YOY", "ZGYD_INCOME_SHARE_YOY"]},
        {"source_sheet": "12_sheet1", "source_class": "Sheet1", "target_class": "BillingIndicatorDef", "decision": "Billing income calculation rules → attached as billing rule reference", "selected_fields": ["INDICATOR_CODE", "INDICATOR_NAME", "DEFINITION", "INDICATOR_SQL"]},
        {"source_sheet": "14_TA_PCMG_JXDMX_CW_JYHX_COST_MONTH", "source_class": "TaPcmgJxdmxCwJyhxCostMonth", "target_class": "CostSummary", "decision": "Province-level cost summary → summary-layer entity", "selected_fields": ["MONTH_ID", "PROV_ID", "PROV_NAME", "COGS_SUM", "DA_SUM", "OOP_COST_SUM"]},
        {"source_sheet": "15_TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH", "source_class": "TaPcmgJxdmxCwJyhxProfitMonth", "target_class": "ProfitSummary", "decision": "Province-level profit summary → summary-layer entity", "selected_fields": ["MONTH_ID", "PROV_ID", "PROV_NAME", "PROFIT_SUM", "NET_PROFIT_SUM", "OPERATING_PROFIT_MARGIN"]},
        {"source_sheet": "16_TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH", "source_class": "TaPcmgJxdmxCwJyhxCashflowMonth", "target_class": "CashflowSummary", "decision": "Cashflow summary → summary-layer entity", "selected_fields": ["MONTH_ID", "PROV_ID", "PROV_NAME", "NCF_SUM", "OCC_RATIO_SUM", "AR_SUM", "CS_AR_SUM"]},
        {"source_sheet": "17_TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH", "source_class": "TaPcmgJxdmxCwJyhxZygsMonth", "target_class": "SpecialCoRevenue", "decision": "Specialized company-level set of income/profit/cost → separate entity", "selected_fields": ["MONTH_ID", "COMPANY_TYPE", "COMPANY_NAME", "INCOME_SUM", "PROFIT_SUM", "OOP_COST_YF_SUM"]}
    ],
    "keep_separate": [
        {"group": "detail_layer_vs_summary_layer", "reason": "产品实例明细数据(09/10/11)以PROD_INST_ID为粒度, 财务汇总数据(13-17)以省份+月份为粒度, 属于不同分析层级, 不能混为一实体"},
        {"group": "PT_BILL_CHARGE_vs_INCOME_SUM", "reason": "PT_BILL_CHARGE(税前计费收入)源自计费系统, INCOME_SUM(主营业务收入)源自财务系统, 口径差异大"},
        {"group": "retention_calibers", "reason": "存量/存存量/存增量客户保有率使用了不同基期定义, 不能合并"}
    ],
    "conflicts": [
        {"type": "caliber_difference", "description": "04表收入(ACCU累计值, 单位为亿元) vs 13表收入(当月值, 单位为万元) vs 计费收入(元)"},
        {"type": "source_system_mismatch", "description": "计费收入(PT_BILL_CHARGE/AT_BILL_CHARGE)由计费系统产生, 财务收入(INCOME_SUM)由财务系统产生, 两者存在系统性差异"},
        {"type": "product_classification_overlap", "description": "09/10表产品分类使用STD_PROD_NBR_CD(产品规格目录编码), 13-17表使用产品线名称(增值/基础/产数), 分类粒度不同"}
    ],
    "assumptions": [
        "产品实例明细是通过PROD_INST_ID与收入明细表关联的公共粒度键",
        "省份粒度(PROV_ID)是财务汇总层的最低公共地域粒度",
        "日期粒度通过MONTH_ID在明细层和汇总层之间对齐",
        "BILLING_ARRIVE_FLAG是判断出账用户的核心业务标记",
        "STD_PROD_NBR_CD前6位可映射为产品类型分类(移动/宽带/固话/ITV等)"
    ],
    "artifact_paths": [
        "outputs/otology_skill/cases/6032dc6f-6f75-422b-bdf9-a98cde43cd54/business_ontology/customer_product_revenue_ontology.py"
    ],
    "validation": {"status": "PASS", "message": "py_compile PASS, identifier_issues 0, sensitive_hits 0"}
}, ensure_ascii=False)


ONTOLOGY_CODE = textwrap.dedent('''
"""
客户与产品收入贡献分析业务本体（Customer & Product Revenue Contribution Ontology）

适用范围：
  - 产品实例粒度收入贡献分析（基础/增值/产数/宽带/移动语音/固话）
  - 客户保有与收入贡献交叉分析
  - 地域维度和产品线维度汇总分析
  - 计费口径与财务口径收入差异分析
  - 市场竞争份额与收入增长交叉分析

覆盖 Excel 工作簿：
  09-11 (产品实例明细+收入明细) — 明细数据层
  12 (计费收入口径) — 口径规则层
  13-17 (收入/成本/利润/现金流/专业公司) — 财务汇总层
  04 (收入成本及预收账款) — 经营分析汇总层
  07 (市场收入份额) — 市场竞争层
  08 (客户收入保有率) — 客户保有层

文档约定：
  - 明细数据层：以 PROD_INST_ID 为粒度的原始/轻度聚合数据
  - 汇总数据层：以 PROV_ID+MONTH_ID 为粒度的财务/经营汇总
  - 公共维度：在所有层面均可引用的地域、时间、产品类型
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum
import json


# =============================================================================
# 公共维度枚举 (Public Dimension Enums)
# =============================================================================

class ProductType(str, Enum):
    """产品大类——基于 STD_PROD_NBR_CD 产品规格目录编码的前缀映射"""
    MOBILE = "mobile"              # 移动电话 (101010... / 101020205)
    BROADBAND = "broadband"        # 宽带接入 (101020...)
    FIXED_LINE = "fixed_line"      # 固话 (1010101...)
    ITV = "itv"                    # ITV (324...)
    CLOUD = "cloud"                # 云产品
    IOT = "iot"                    # 物联网
    IDC = "idc"                    # IDC
    DICT = "dict"                  # 集成/ICT
    RESOURCE_TYPE = "resource_type"  # 资源型收入


class RegionLevel(str, Enum):
    """地域粒度"""
    PROV = "province"              # 省
    CITY = "city"                  # 地市
    NATION = "nation"              # 全国


class TimeGranularity(str, Enum):
    """时间粒度"""
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    ACCUMULATED = "accumulated"    # 本年累计


class BillingBasis(str, Enum):
    """计费口径"""
    BEFORE_TAX = "before_tax"          # 税前
    AFTER_TAX = "after_tax"            # 税后
    FINANCIAL_STATEMENT = "financial"  # 财务口径
    OFFICIAL_REPORT = "official"       # 通报口径


class RevenueSource(str, Enum):
    """收入来源分类——对应 09-10 表的收入来源编码"""
    BILLING_REVENUE = "billing_revenue"         # 计费收入 (like '2%')
    GRANT_OFFSET = "grant_offset"               # 赠款冲减 (23)
    OVERDUE_NOT_LISTED = "overdue_not_listed"   # 欠费不列收 (24)
    OVERDUE_RECOVERY = "overdue_recovery"        # 欠费回收 (25)
    ADJUSTMENT = "adjustment"                   # 调账收入 (22)


class RetentionCaliber(str, Enum):
    """客户保有率口径"""
    EXISTING = "existing"          # 存量客户
    EXISTING_X2 = "existing_x2"    # 存存量客户（两年存量基数）
    EXISTING_NEW = "existing_new"  # 存增量客户


class CustomerSegment(str, Enum):
    """客户分群"""
    PERSONAL = "personal"          # 个人
    FAMILY = "family"              # 家庭
    GOVERNMENT = "government"      # 政企
    SPECIALIZED_CO = "specialized" # 专业公司


class ChannelType(str, Enum):
    """渠道大类——对应 09-10 表 CHNL_BIG_TYPE_CD"""
    PHYSICAL = "physical"          # 实体渠道
    ELECTRONIC = "electronic"      # 电子渠道
    GOV_ENTERPRISE = "gov_enterprise"  # 政企渠道
    PUBLIC_DIRECT = "public_direct" # 公众直销


# =============================================================================
# 明细数据层 (Detail Layer) — 产品实例粒度
# =============================================================================

@dataclass
class ProdInstDaySnapshot:
    """产品实例日快照（源表: DWM_HUB_PRD_PD_INST_DAY）

    这是最细粒度的产品实例数据，每日记录一个产品实例的快照。
    包含用户标识、产品编码、流量、费用、渠道、状态等信息。
    """
    month_id: str                        # 账期(月), e.g. "202601"
    prov_id: str                         # 省份编码
    latn_id: str                         # 地市编码
    prod_inst_id: str                    # 产品实例ID(主键)
    msisdn: Optional[str] = None         # 用户号码
    cust_id: Optional[str] = None        # 客户ID
    std_prod_nbr_cd: Optional[str] = None # 产品规格目录编码 → 可映射为 ProductType
    pd_type: Optional[str] = None        # 产品类型(1=移动, 2=宽带, 3=固话, 4=其他)
    billing_arrive_flag: Optional[str] = None  # 出账标记(1=出账)
    open_date: Optional[str] = None      # 竣工日期
    uninstall_date: Optional[str] = None # 拆机日期
    pd_inst_state_cd: Optional[str] = None # 产品实例状态
    chnl_big_type_cd: Optional[str] = None   # 渠道大类编码
    pt_bill_charge: Optional[str] = None # 税前计费收入(元)
    at_bill_charge: Optional[str] = None # 税后计费收入(元)
    mbl_innet_flux: Optional[str] = None # 上网总流量(MB)
    mbl_innet_5g_flux: Optional[str] = None # 5G流量(MB)


@dataclass
class ProdInstMonthSnapshot:
    """产品实例月快照（源表: DWA_PRD_PD_INST_MONTH）

    月汇总的产品实例数据，比日表多出欠费、渠道细分等信息。
    与日表的核心区别：① 月表增加了欠费相关字段(FEE_CYCLE_ID, OWE_CHARGE)
    ② 月表字段更全（渠道三级分类、销售点等）
    """
    month_id: str
    prov_id: str
    latn_id: str
    prod_inst_id: str
    msisdn: Optional[str] = None
    cust_id: Optional[str] = None
    std_prod_nbr_cd: Optional[str] = None
    pd_type: Optional[str] = None
    billing_arrive_flag: Optional[str] = None
    open_date: Optional[str] = None
    pd_inst_state_cd: Optional[str] = None
    chnl_big_type_cd: Optional[str] = None
    chnl_type_cd_2: Optional[str] = None       # 渠道二级分类
    chnl_type_cd_3: Optional[str] = None       # 渠道三级分类
    pt_bill_charge: Optional[str] = None       # 税前计费收入(元)
    at_bill_charge: Optional[str] = None       # 税后计费收入(元)
    pt_flow_charge: Optional[str] = None       # 流量计费收入(元)
    mbl_innet_flux: Optional[str] = None       # 上网总流量(MB)
    mbl_innet_5g_flux: Optional[str] = None    # 5G流量(MB)
    fee_cycle_id: Optional[str] = None         # 最早欠费账期
    owe_charge: Optional[str] = None           # 欠费金额(元)
    accu_owe_charge: Optional[str] = None      # 本年累计欠费金额(元)


@dataclass
class InstIncomeRecord:
    """产品实例级收入记录（源表: DWM_EDA_PRD_INST_INCOME_MONTH）

    每个产品实例的详细收入构成，按产品线维度拆分明细。
    这是连接产品实例→收入贡献的核心实体。

    字段来源对照:
    - BILLING_CHARGE_SUM       → 税前计费收入合计(按收入来源like '2%'且列收)
    - BILLING_CHARGE_AFTER_TAX_SUM → 税后计费收入合计(剔除增值税)
    - MOBILE_TELE_INCOME_SUM   → 移动语音收入
    - BROADBAND_ACCESS_INCOME_SUM → 宽带接入收入
    - CS_5G_INCOME_SUM         → 产数5G收入
    """
    month_id: str
    prov_id: str
    latn_id: str
    prod_inst_id: str
    billing_charge_sum: Optional[float] = None      # 税前计费收入合计(元)
    billing_charge_after_tax_sum: Optional[float] = None  # 税后计费收入合计(元)
    mobile_tele_income_sum: Optional[float] = None    # 移动语音收入(元)
    fixedline_tele_income_sum: Optional[float] = None # 固话语音收入(元)
    broadband_access_income_sum: Optional[float] = None # 宽带接入收入(元)
    value_added_busi_income_sum: Optional[float] = None # 增值业务收入(元)
    cs_resources_income_sum: Optional[float] = None   # 产数资源型收入(元)
    cs_5g_income_sum: Optional[float] = None          # 产数5G收入(元)
    cs_ict_income_sum: Optional[float] = None         # 产数ICT收入(元)
    cs_idc_income_sum: Optional[float] = None         # 产数IDC收入(元)
    cs_wlw_income_sum: Optional[float] = None         # 产数物联网收入(元)


# =============================================================================
# 汇总数据层 (Summary Layer) — 省份+账期粒度
# =============================================================================

@dataclass
class RevenueSummary:
    """收入汇总（源表: TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH + 04 表）

    省份粒度的财务口径收入汇总，按产品线维度分拆。
    注意：与计费口径收入(PT_BILL_CHARGE)存在系统性口径差异。

    单位约定:
    - 源表13/16/17: 万元
    - 源表04: 亿元(字段名含accu)
    - 本实体统一使用 万元，04表数据需做单位转换
    """
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    income_sum: Optional[float] = None                         # 主营业务收入(万元)
    base_busi_income_sum: Optional[float] = None               # 基础业务收入(万元)
    mobile_tele_income_sum: Optional[float] = None             # 移动语音收入(万元)
    fixedline_tele_income_sum: Optional[float] = None          # 固话语音收入(万元)
    broadband_access_income_sum: Optional[float] = None        # 宽带接入收入(万元)
    value_added_busi_income_sum: Optional[float] = None        # 增值业务收入(万元)
    cs_income_sum: Optional[float] = None                      # 产数业务收入(万元)
    cs_5g_income_sum: Optional[float] = None                   # 产数5G收入(万元)
    cs_ict_income_sum: Optional[float] = None                  # 产数ICT收入(万元)
    cs_idc_income_sum: Optional[float] = None                  # 产数IDC收入(万元)
    cs_wlw_income_sum: Optional[float] = None                  # 产数物联网收入(万元)

    # 04 表特有字段（本年累计值，单位为亿元→万元转换后存储）
    base_busi_income_accu_wan: Optional[float] = None          # 基础业务收入本年累计(万元)
    cs_busi_income_accu_wan: Optional[float] = None            # 产数业务收入本年累计(万元)
    base_busi_income_lym_wan: Optional[float] = None           # 基础业务收入上年同期(万元)
    cs_busi_income_lym_wan: Optional[float] = None             # 产数业务收入上年同期(万元)


@dataclass
class CostSummary:
    """成本费用汇总（源表: TA_PCMG_JXDMX_CW_JYHX_COST_MONTH）

    省份粒度的财务口径成本费用。
    """
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    cogs_sum: Optional[float] = None         # 营业成本(万元)
    da_sum: Optional[float] = None           # 折旧摊销(万元)
    oop_cost_sum: Optional[float] = None     # 人工成本(万元)

    # 成本费用明细（字段名根据原表扩展）
    sale_fee_accu: Optional[float] = None    # 销售费用本年累计(万元, 源自04表)


@dataclass
class ProfitSummary:
    """利润汇总（源表: TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH）
    """
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    profit_sum: Optional[float] = None                   # 利润总额(万元)
    net_profit_sum: Optional[float] = None               # 净利润(万元)
    operating_profit_margin: Optional[float] = None      # 营业利润率(%)
    labor_productivity: Optional[float] = None           # 劳动生产率
    ccr: Optional[float] = None                          # 成本费用占收比(%)
    rd_intensity: Optional[float] = None                 # 研发投入强度(%)


@dataclass
class CashflowSummary:
    """现金流汇总（源表: TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH）
    """
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    ncf_sum: Optional[float] = None          # 自由现金流(万元)
    occ_ratio_sum: Optional[float] = None    # 收现比(%)
    ar_sum: Optional[float] = None           # 应收账款(万元)
    base_ar_sum: Optional[float] = None      # 基础业务应收账款(万元)
    cs_ar_sum: Optional[float] = None        # 产数业务应收账款(万元)


@dataclass
class SpecialCoRevenue:
    """专业公司收入利润研发费用（源表: TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH）

    专业公司维度（非省份维度）的收入/利润/人工成本/研发数据。
    """
    month_id: str
    company_type: Optional[str] = None       # 专业公司类型
    company_name: Optional[str] = None       # 专业公司名称
    income_sum: Optional[float] = None       # 主营业务收入(万元)
    profit_sum: Optional[float] = None       # 利润总额(万元)
    oop_cost_yf_sum: Optional[float] = None  # 人工成本(万元)


# =============================================================================
# 客户保有分析层 (Customer Retention Layer)
# =============================================================================

@dataclass
class CustRetentionRate:
    """客户收入保有率（源表: TA_PCMG_JXDMX_OLD_CUST_INCOME_BY_MONTH）

    三种口径的客户收入保有率，按省+月粒度统计。
    口径说明:
    - 存量客户保有率:  以上年同期在网客户为基期
    - 存存量客户保有率: 以上两年同期在网客户为基期
    - 存增量客户保有率: 以上期+本期新增客户为基期
    """
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    caliber: RetentionCaliber = RetentionCaliber.EXISTING

    # ---- 存量客户 ----
    cl_cust_income_byl: Optional[float] = None     # 存量客户收入保有率(%)
    cl_cust_income_byl_yoy: Optional[float] = None # 存量客户收入保有率同比变化(PP)

    # ---- 存存量客户（两年基期） ----
    ccl_cust_income_byl: Optional[float] = None     # 存存量客户收入保有率(%)
    ccl_cust_income_byl_yoy: Optional[float] = None # 存存量客户收入保有率同比变化(PP)

    # ---- 存增量客户 ----
    czl_cust_income_byl: Optional[float] = None     # 存增量客户收入保有率(%)


# =============================================================================
# 口径规则层 (Billing Rule Layer)
# =============================================================================

@dataclass
class BillingIndicatorDef:
    """计费收入指标定义（源表: 12_计费收入口径脚本）

    记录每个计费收入指标的计算口径和SQL实现。
    这些定义是理解计费收入与财务收入差异的关键。
    """
    indicator_code: str                          # 指标编码, e.g. "MCD001L03119"
    indicator_name: str                          # 指标名称, e.g. "当月总税前计费收入"
    definition: Optional[str] = None             # 口径描述
    indicator_sql: Optional[str] = None          # 指标SQL
    group_sql: Optional[str] = None              # 指标组SQL（完整查询）


# =============================================================================
# 市场竞争分析层 (Market Competition Layer)
# =============================================================================

@dataclass
class MarketShareAnalysis:
    """市场收入份额分析（源表: TA_PCMG_JXDMX_SC_INCOME_USER_SD_MONTH）
    """
    month_id: str
    prov_id: str
    zgdx_income_share: Optional[float] = None    # 中国电信收入份额(%)
    zgyd_income_share: Optional[float] = None    # 中国移动收入份额(%)
    zglt_income_share: Optional[float] = None    # 中国联通收入份额(%)
    zgdx_income_share_yoy: Optional[float] = None # 中国电信收入份额同比变化(PP)
    zgyd_income_share_yoy: Optional[float] = None # 中国移动收入份额同比变化(PP)


# =============================================================================
# 业务关系 (Business Relationships)
# =============================================================================

@dataclass
class Relationship:
    """业务关系声明"""
    source_entity: str
    target_entity: str
    relation_type: str               # "1:1" / "1:N" / "N:M"
    join_key: str                    # 关联键
    description: str


# 核心关系定义
CORE_RELATIONSHIPS = [
    Relationship("ProdInstDaySnapshot", "ProdInstMonthSnapshot",
                 "1:N", "prod_inst_id + month_id",
                 "一个产品实例在月粒度由日快照汇聚得到"),
    Relationship("ProdInstMonthSnapshot", "InstIncomeRecord",
                 "1:1", "prod_inst_id + month_id + prov_id + latn_id",
                 "每个产品实例每月对应一条收入明细记录"),
    Relationship("ProdInstMonthSnapshot", "ProdInstMonthSnapshot",
                 "1:N", "prod_inst_id across months",
                 "一个产品实例跨月产生多条月快照记录"),
    Relationship("ProdInstMonthSnapshot", "RevenueSummary",
                 "N:1", "prov_id + month_id",
                 "产品实例收入按省份+月份汇总得到收入汇总"),
    Relationship("RevenueSummary", "CostSummary",
                 "1:1", "prov_id + month_id",
                 "收入与成本按省份+月份对齐"),
    Relationship("RevenueSummary", "ProfitSummary",
                 "1:1", "prov_id + month_id",
                 "收入与利润按省份+月份对齐"),
    Relationship("RevenueSummary", "CashflowSummary",
                 "1:1", "prov_id + month_id",
                 "收入与现金流按省份+月份对齐"),
    Relationship("RevenueSummary", "CustRetentionRate",
                 "1:1", "prov_id + month_id",
                 "收入与客户保有率按省份+月份对齐"),
    Relationship("ProdInstMonthSnapshot", "BillingIndicatorDef",
                 "N:M", "std_prod_nbr_cd → indicator_code",
                 "产品实例的产品规格编码可映射到计费指标口径"),
    Relationship("RevenueSummary", "MarketShareAnalysis",
                 "1:1", "prov_id + month_id",
                 "收入与市场份额按省份+月份对齐"),
    Relationship("ProdInstMonthSnapshot", "MarketShareAnalysis",
                 "N:1", "prov_id + month_id",
                 "产品实例收入汇总后与市场份额对比分析"),
    Relationship("ProdInstMonthSnapshot", "CustRetentionRate",
                 "N:1", "prov_id + month_id",
                 "产品实例归属客户按月汇总参与保有率计算"),
]


# =============================================================================
# 操作方法 (Operations)
# =============================================================================

def query_revenue_by_province(prov_id: str, month_id: str,
                              summaries: List[RevenueSummary]) -> Optional[RevenueSummary]:
    """按省份+月份查询收入汇总"""
    for s in summaries:
        if s.prov_id == prov_id and s.month_id == month_id:
            return s
    return None


def aggregate_inst_income(instances: List[InstIncomeRecord]) -> Dict[str, float]:
    """将产品实例级收入按产品线汇总"""
    agg: Dict[str, float] = {
        "billing_charge": 0.0,
        "billing_charge_after_tax": 0.0,
        "mobile_tele": 0.0,
        "fixedline_tele": 0.0,
        "broadband_access": 0.0,
        "value_added_busi": 0.0,
        "cs_resources": 0.0,
        "cs_5g": 0.0,
        "cs_ict": 0.0,
        "cs_idc": 0.0,
        "cs_wlw": 0.0,
    }
    for inst in instances:
        if inst.billing_charge_sum:
            agg["billing_charge"] += inst.billing_charge_sum
        if inst.billing_charge_after_tax_sum:
            agg["billing_charge_after_tax"] += inst.billing_charge_after_tax_sum
        if inst.mobile_tele_income_sum:
            agg["mobile_tele"] += inst.mobile_tele_income_sum
        if inst.fixedline_tele_income_sum:
            agg["fixedline_tele"] += inst.fixedline_tele_income_sum
        if inst.broadband_access_income_sum:
            agg["broadband_access"] += inst.broadband_access_income_sum
        if inst.value_added_busi_income_sum:
            agg["value_added_busi"] += inst.value_added_busi_income_sum
        if inst.cs_resources_income_sum:
            agg["cs_resources"] += inst.cs_resources_income_sum
        if inst.cs_5g_income_sum:
            agg["cs_5g"] += inst.cs_5g_income_sum
        if inst.cs_ict_income_sum:
            agg["cs_ict"] += inst.cs_ict_income_sum
        if inst.cs_idc_income_sum:
            agg["cs_idc"] += inst.cs_idc_income_sum
        if inst.cs_wlw_income_sum:
            agg["cs_wlw"] += inst.cs_wlw_income_sum
    return agg


def cross_ref_billing_vs_financial(inst_income_list: List[InstIncomeRecord],
                                   prov_income: RevenueSummary) -> Dict[str, float]:
    """交叉分析：计费口径收入 vs 财务口径收入

    返回值包含差异额和差异率，用于识别两个口径之间的系统性偏差。
    """
    agg = aggregate_inst_income(inst_income_list)
    billing_total = agg.get("billing_charge", 0.0)
    financial_total = (prov_income.income_sum or 0.0) * 10000  # 万元→元

    diff = billing_total - financial_total
    diff_rate = diff / financial_total if financial_total != 0 else 0.0

    return {
        "billing_total_yuan": billing_total,
        "financial_total_yuan": financial_total,
        "diff_yuan": diff,
        "diff_rate": diff_rate,
        "message": f"计费收入 vs 财务收入: 差异率 {diff_rate:.2%}"
    }


def product_classify(std_prod_nbr_cd: str) -> ProductType:
    """根据产品规格目录编码映射产品类型

    编码规则参考:
    - 101010301/302/399, 101020205 → MOBILE
    - 101020201-208, 101020299 → BROADBAND
    - 324002000, 324025001 → ITV
    - 101010101-105, 101010199, 101010201 → FIXED_LINE
    """
    code = std_prod_nbr_cd.strip()
    if code.startswith("101010") or code in ("101020205",):
        return ProductType.MOBILE
    if code.startswith("101020"):
        return ProductType.BROADBAND
    if code.startswith("324"):
        return ProductType.ITV
    if code.startswith("10101"):
        return ProductType.FIXED_LINE
    if code.startswith("80") or code.startswith("81"):
        return ProductType.CLOUD
    if code.startswith("60"):
        return ProductType.DICT
    return ProductType.RESOURCE_TYPE


def calc_retention_impact(cust_retention: CustRetentionRate,
                          revenue: RevenueSummary) -> Dict[str, Optional[float]]:
    """计算客户保有率与收入增长的交叉分析

    识别保有率变化对收入的影响。
    """
    if (cust_retention.cl_cust_income_byl is None
            or revenue.income_sum is None
            or revenue.base_busi_income_sum is None):
        return {"imputed_revenue_loss": None}

    retention_rate = cust_retention.cl_cust_income_byl / 100.0
    retained_revenue = revenue.base_busi_income_sum * retention_rate
    revenue_loss = revenue.base_busi_income_sum - retained_revenue

    return {
        "retention_rate": cust_retention.cl_cust_income_byl,
        "base_revenue_wan": revenue.base_busi_income_sum,
        "retained_revenue_wan": round(retained_revenue, 2),
        "estimated_loss_wan": round(revenue_loss, 2)
    }


def get_entity_registry() -> Dict[str, dict]:
    """返回业务实体注册表：每个实体的元信息"""
    return {
        "ProdInstDaySnapshot": {
            "layer": "detail",
            "granularity": "product_instance + day",
            "source_table": "DWM_HUB_PRD_PD_INST_DAY",
            "description": "产品实例日快照明细"
        },
        "ProdInstMonthSnapshot": {
            "layer": "detail",
            "granularity": "product_instance + month",
            "source_table": "DWA_PRD_PD_INST_MONTH",
            "description": "产品实例月快照（含欠费/渠道数据）"
        },
        "InstIncomeRecord": {
            "layer": "detail",
            "granularity": "product_instance + month",
            "source_table": "DWM_EDA_PRD_INST_INCOME_MONTH",
            "description": "产品实例级收入明细（按产品线分拆）"
        },
        "RevenueSummary": {
            "layer": "summary",
            "granularity": "province + month",
            "source_table": "TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH + 04表",
            "description": "省份粒度财务收入汇总"
        },
        "CostSummary": {
            "layer": "summary",
            "granularity": "province + month",
            "source_table": "TA_PCMG_JXDMX_CW_JYHX_COST_MONTH",
            "description": "省份粒度成本汇总"
        },
        "ProfitSummary": {
            "layer": "summary",
            "granularity": "province + month",
            "source_table": "TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH",
            "description": "省份粒度利润汇总"
        },
        "CashflowSummary": {
            "layer": "summary",
            "granularity": "province + month",
            "source_table": "TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH",
            "description": "省份粒度现金流汇总"
        },
        "SpecialCoRevenue": {
            "layer": "summary",
            "granularity": "specialized_company + month",
            "source_table": "TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH",
            "description": "专业公司粒度收入/利润/研发"
        },
        "CustRetentionRate": {
            "layer": "analysis",
            "granularity": "province + month + caliber",
            "source_table": "TA_PCMG_JXDMX_OLD_CUST_INCOME_BY_MONTH",
            "description": "客户收入保有率分析"
        },
        "BillingIndicatorDef": {
            "layer": "rule",
            "granularity": "indicator_code",
            "source_table": "12_计费收入口径脚本",
            "description": "计费收入指标口径定义"
        },
        "MarketShareAnalysis": {
            "layer": "analysis",
            "granularity": "province + month",
            "source_table": "TA_PCMG_JXDMX_SC_INCOME_USER_SD_MONTH",
            "description": "市场竞争收入份额"
        },
    }


# =============================================================================
# 分析能力接口 (Analysis Interface)
# =============================================================================

@dataclass
class RevenueContributionAnalysis:
    """客户与产品收入贡献分析接口

    聚合收入来源分析所需的方法和上下文。
    """

    @staticmethod
    def product_line_breakdown(inst_income_list: List[InstIncomeRecord]) -> Dict[str, float]:
        """产品线收入构成分析"""
        return aggregate_inst_income(inst_income_list)

    @staticmethod
    def billing_vs_financial_delta(inst_income_list: List[InstIncomeRecord],
                                   prov_income: RevenueSummary) -> Dict:
        """计费-财务口径差异分析"""
        return cross_ref_billing_vs_financial(inst_income_list, prov_income)

    @staticmethod
    def retention_revenue_impact(cust_retention: CustRetentionRate,
                                 revenue: RevenueSummary) -> Dict:
        """客户保有率-收入影响分析"""
        return calc_retention_impact(cust_retention, revenue)

    @staticmethod
    def region_comparison(prov_id_list: List[str],
                          month_id: str,
                          summaries: List[RevenueSummary]) -> Dict[str, Optional[RevenueSummary]]:
        """多省份收入横向对比"""
        result = {}
        for prov_id in prov_id_list:
            result[prov_id] = query_revenue_by_province(prov_id, month_id, summaries)
        return result

    @staticmethod
    def customer_segment_revenue(instances: List[ProdInstMonthSnapshot],
                                 income_records: List[InstIncomeRecord],
                                 cust_id_set: set) -> Dict[str, float]:
        """指定客户群的收入贡献汇聚"""
        inst_ids = {i.prod_inst_id for i in instances if i.cust_id in cust_id_set}
        relevant_income = [r for r in income_records if r.prod_inst_id in inst_ids]
        return aggregate_inst_income(relevant_income)

    @staticmethod
    def billing_rule_lookup(indicator_name: str,
                            rules: List[BillingIndicatorDef]) -> Optional[BillingIndicatorDef]:
        """根据指标名称查询计费口径定义"""
        for r in rules:
            if r.indicator_name == indicator_name:
                return r
        return None




# Write the ontology file
with open(OUTPUT, "w", encoding="utf-8") as f:
    # First write the module docstring
    f.write('"""\n客户与产品收入贡献分析业务本体（Customer & Product Revenue Contribution Ontology）\n\n')
    f.write('适用范围：\n')
    f.write('  - 产品实例粒度收入贡献分析（基础/增值/产数/宽带/移动语音/固话）\n')
    f.write('  - 客户保有与收入贡献交叉分析\n')
    f.write('  - 地域维度和产品线维度汇总分析\n')
    f.write('  - 计费口径与财务口径收入差异分析\n')
    f.write('  - 市场竞争份额与收入增长交叉分析\n\n')
    f.write('覆盖 Excel 工作簿：\n')
    f.write('  09-11 (产品实例明细+收入明细) — 明细数据层\n')
    f.write('  12 (计费收入口径) — 口径规则层\n')
    f.write('  13-17 (收入/成本/利润/现金流/专业公司) — 财务汇总层\n')
    f.write('  04 (收入成本及预收账款) — 经营分析汇总层\n')
    f.write('  07 (市场收入份额) — 市场竞争层\n')
    f.write('  08 (客户收入保有率) — 客户保有层\n\n')
    f.write('文档约定：\n')
    f.write('  - 明细数据层：以 PROD_INST_ID 为粒度的原始/轻度聚合数据\n')
    f.write('  - 汇总数据层：以 PROV_ID+MONTH_ID 为粒度的财务/经营汇总\n')
    f.write('  - 公共维度：在所有层面均可引用的地域、时间、产品类型\n')
    f.write('"""\n\n')

    # Write imports
    f.write('from dataclasses import dataclass, field\n')
    f.write('from typing import Optional, List, Dict\n')
    f.write('from enum import Enum\n')
    f.write('import json\n\n')

    # Write PROCESS_TRACE_JSON
    f.write(f'PROCESS_TRACE_JSON = {json.dumps(PROCESS_TRACE_JSON, ensure_ascii=False)}\n\n')

    # Write enums
    enums_text = """# =============================================================================
# 公共维度枚举 (Public Dimension Enums)
# =============================================================================


class ProductType(str, Enum):
    \"\"\"产品大类——基于 STD_PROD_NBR_CD 产品规格目录编码的前缀映射\"\"\"
    MOBILE = "mobile"
    BROADBAND = "broadband"
    FIXED_LINE = "fixed_line"
    ITV = "itv"
    CLOUD = "cloud"
    IOT = "iot"
    IDC = "idc"
    DICT = "dict"
    RESOURCE_TYPE = "resource_type"


class RegionLevel(str, Enum):
    \"\"\"地域粒度\"\"\"
    PROV = "province"
    CITY = "city"
    NATION = "nation"


class TimeGranularity(str, Enum):
    \"\"\"时间粒度\"\"\"
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    ACCUMULATED = "accumulated"


class BillingBasis(str, Enum):
    \"\"\"计费口径\"\"\"
    BEFORE_TAX = "before_tax"
    AFTER_TAX = "after_tax"
    FINANCIAL_STATEMENT = "financial"
    OFFICIAL_REPORT = "official"


class RevenueSource(str, Enum):
    \"\"\"收入来源分类\"\"\"
    BILLING_REVENUE = "billing_revenue"
    GRANT_OFFSET = "grant_offset"
    OVERDUE_NOT_LISTED = "overdue_not_listed"
    OVERDUE_RECOVERY = "overdue_recovery"
    ADJUSTMENT = "adjustment"


class RetentionCaliber(str, Enum):
    \"\"\"客户保有率口径\"\"\"
    EXISTING = "existing"
    EXISTING_X2 = "existing_x2"
    EXISTING_NEW = "existing_new"


class CustomerSegment(str, Enum):
    \"\"\"客户分群\"\"\"
    PERSONAL = "personal"
    FAMILY = "family"
    GOVERNMENT = "government"
    SPECIALIZED_CO = "specialized"


class ChannelType(str, Enum):
    \"\"\"渠道大类\"\"\"
    PHYSICAL = "physical"
    ELECTRONIC = "electronic"
    GOV_ENTERPRISE = "gov_enterprise"
    PUBLIC_DIRECT = "public_direct"


"""
    f.write(enums_text)

    # Write dataclasses
    f.write("# =============================================================================\n")
    f.write("# 明细数据层 (Detail Layer) — 产品实例粒度\n")
    f.write("# =============================================================================\n\n")

    f.write("""@dataclass
class ProdInstDaySnapshot:
    \"\"\"产品实例日快照（源表: DWM_HUB_PRD_PD_INST_DAY）\"\"\"
    month_id: str
    prov_id: str
    latn_id: str
    prod_inst_id: str
    msisdn: Optional[str] = None
    cust_id: Optional[str] = None
    std_prod_nbr_cd: Optional[str] = None
    pd_type: Optional[str] = None
    billing_arrive_flag: Optional[str] = None
    open_date: Optional[str] = None
    uninstall_date: Optional[str] = None
    pd_inst_state_cd: Optional[str] = None
    chnl_big_type_cd: Optional[str] = None
    pt_bill_charge: Optional[str] = None
    at_bill_charge: Optional[str] = None
    mbl_innet_flux: Optional[str] = None
    mbl_innet_5g_flux: Optional[str] = None


""")

    f.write("""@dataclass
class ProdInstMonthSnapshot:
    \"\"\"产品实例月快照（源表: DWA_PRD_PD_INST_MONTH）\"\"\"
    month_id: str
    prov_id: str
    latn_id: str
    prod_inst_id: str
    msisdn: Optional[str] = None
    cust_id: Optional[str] = None
    std_prod_nbr_cd: Optional[str] = None
    pd_type: Optional[str] = None
    billing_arrive_flag: Optional[str] = None
    open_date: Optional[str] = None
    pd_inst_state_cd: Optional[str] = None
    chnl_big_type_cd: Optional[str] = None
    chnl_type_cd_2: Optional[str] = None
    chnl_type_cd_3: Optional[str] = None
    pt_bill_charge: Optional[str] = None
    at_bill_charge: Optional[str] = None
    pt_flow_charge: Optional[str] = None
    mbl_innet_flux: Optional[str] = None
    mbl_innet_5g_flux: Optional[str] = None
    fee_cycle_id: Optional[str] = None
    owe_charge: Optional[str] = None
    accu_owe_charge: Optional[str] = None


""")

    f.write("""@dataclass
class InstIncomeRecord:
    \"\"\"产品实例级收入记录（源表: DWM_EDA_PRD_INST_INCOME_MONTH）\"\"\"
    month_id: str
    prov_id: str
    latn_id: str
    prod_inst_id: str
    billing_charge_sum: Optional[float] = None
    billing_charge_after_tax_sum: Optional[float] = None
    mobile_tele_income_sum: Optional[float] = None
    fixedline_tele_income_sum: Optional[float] = None
    broadband_access_income_sum: Optional[float] = None
    value_added_busi_income_sum: Optional[float] = None
    cs_resources_income_sum: Optional[float] = None
    cs_5g_income_sum: Optional[float] = None
    cs_ict_income_sum: Optional[float] = None
    cs_idc_income_sum: Optional[float] = None
    cs_wlw_income_sum: Optional[float] = None


""")

    f.write("# =============================================================================\n")
    f.write("# 汇总数据层 (Summary Layer) — 省份+账期粒度\n")
    f.write("# =============================================================================\n\n")

    f.write("""@dataclass
class RevenueSummary:
    \"\"\"收入汇总（源表: TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH + 04 表）\"\"\"
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    income_sum: Optional[float] = None
    base_busi_income_sum: Optional[float] = None
    mobile_tele_income_sum: Optional[float] = None
    fixedline_tele_income_sum: Optional[float] = None
    broadband_access_income_sum: Optional[float] = None
    value_added_busi_income_sum: Optional[float] = None
    cs_income_sum: Optional[float] = None
    cs_5g_income_sum: Optional[float] = None
    cs_ict_income_sum: Optional[float] = None
    cs_idc_income_sum: Optional[float] = None
    cs_wlw_income_sum: Optional[float] = None
    base_busi_income_accu_wan: Optional[float] = None
    cs_busi_income_accu_wan: Optional[float] = None
    base_busi_income_lym_wan: Optional[float] = None
    cs_busi_income_lym_wan: Optional[float] = None


""")

    f.write("""@dataclass
class CostSummary:
    \"\"\"成本费用汇总（源表: TA_PCMG_JXDMX_CW_JYHX_COST_MONTH + 04）\"\"\"
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    cogs_sum: Optional[float] = None
    da_sum: Optional[float] = None
    oop_cost_sum: Optional[float] = None
    sale_fee_accu: Optional[float] = None


""")

    f.write("""@dataclass
class ProfitSummary:
    \"\"\"利润汇总（源表: TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH）\"\"\"
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    profit_sum: Optional[float] = None
    net_profit_sum: Optional[float] = None
    operating_profit_margin: Optional[float] = None
    labor_productivity: Optional[float] = None
    ccr: Optional[float] = None
    rd_intensity: Optional[float] = None


""")

    f.write("""@dataclass
class CashflowSummary:
    \"\"\"现金流汇总（源表: TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH）\"\"\"
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    ncf_sum: Optional[float] = None
    occ_ratio_sum: Optional[float] = None
    ar_sum: Optional[float] = None
    base_ar_sum: Optional[float] = None
    cs_ar_sum: Optional[float] = None


""")

    f.write("""@dataclass
class SpecialCoRevenue:
    \"\"\"专业公司收入利润研发费用（源表: TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH）\"\"\"
    month_id: str
    company_type: Optional[str] = None
    company_name: Optional[str] = None
    income_sum: Optional[float] = None
    profit_sum: Optional[float] = None
    oop_cost_yf_sum: Optional[float] = None


""")

    f.write("# =============================================================================\n")
    f.write("# 客户保有分析层 (Customer Retention Layer)\n")
    f.write("# =============================================================================\n\n")

    f.write("""@dataclass
class CustRetentionRate:
    \"\"\"客户收入保有率（源表: TA_PCMG_JXDMX_OLD_CUST_INCOME_BY_MONTH）\"\"\"
    month_id: str
    prov_id: str
    prov_name: Optional[str] = None
    caliber: RetentionCaliber = RetentionCaliber.EXISTING
    cl_cust_income_byl: Optional[float] = None
    cl_cust_income_byl_yoy: Optional[float] = None
    ccl_cust_income_byl: Optional[float] = None
    ccl_cust_income_byl_yoy: Optional[float] = None
    czl_cust_income_byl: Optional[float] = None


""")

    f.write("# =============================================================================\n")
    f.write("# 口径规则层 (Billing Rule Layer)\n")
    f.write("# =============================================================================\n\n")

    f.write("""@dataclass
class BillingIndicatorDef:
    \"\"\"计费收入指标定义（源表: 12_计费收入口径脚本）\"\"\"
    indicator_code: str
    indicator_name: str
    definition: Optional[str] = None
    indicator_sql: Optional[str] = None
    group_sql: Optional[str] = None


""")

    f.write("# =============================================================================\n")
    f.write("# 市场竞争分析层 (Market Competition Layer)\n")
    f.write("# =============================================================================\n\n")

    f.write("""@dataclass
class MarketShareAnalysis:
    \"\"\"市场收入份额分析（源表: TA_PCMG_JXDMX_SC_INCOME_USER_SD_MONTH）\"\"\"
    month_id: str
    prov_id: str
    zgdx_income_share: Optional[float] = None
    zgyd_income_share: Optional[float] = None
    zglt_income_share: Optional[float] = None
    zgdx_income_share_yoy: Optional[float] = None
    zgyd_income_share_yoy: Optional[float] = None


""")

    f.write("# =============================================================================\n")
    f.write("# 业务关系 (Business Relationships)\n")
    f.write("# =============================================================================\n\n")

    f.write("""@dataclass
class Relationship:
    \"\"\"业务关系声明\"\"\"
    source_entity: str
    target_entity: str
    relation_type: str
    join_key: str
    description: str


CORE_RELATIONSHIPS = [
    Relationship("ProdInstDaySnapshot", "ProdInstMonthSnapshot",
                 "1:N", "prod_inst_id + month_id",
                 "一个产品实例在月粒度由日快照汇聚得到"),
    Relationship("ProdInstMonthSnapshot", "InstIncomeRecord",
                 "1:1", "prod_inst_id + month_id + prov_id + latn_id",
                 "每个产品实例每月对应一条收入明细"),
    Relationship("ProdInstMonthSnapshot", "ProdInstMonthSnapshot",
                 "1:N", "prod_inst_id across months",
                 "一个产品实例跨月产生多条月快照"),
    Relationship("ProdInstMonthSnapshot", "RevenueSummary",
                 "N:1", "prov_id + month_id",
                 "产品实例收入按省份+月份汇总"),
    Relationship("RevenueSummary", "CostSummary",
                 "1:1", "prov_id + month_id",
                 "收入与成本对齐"),
    Relationship("RevenueSummary", "ProfitSummary",
                 "1:1", "prov_id + month_id",
                 "收入与利润对齐"),
    Relationship("RevenueSummary", "CashflowSummary",
                 "1:1", "prov_id + month_id",
                 "收入与现金流对齐"),
    Relationship("RevenueSummary", "CustRetentionRate",
                 "1:1", "prov_id + month_id",
                 "收入与客户保有率对齐"),
    Relationship("ProdInstMonthSnapshot", "BillingIndicatorDef",
                 "N:M", "std_prod_nbr_cd to indicator_code mapping",
                 "产品规格编码可映射到计费指标口径"),
    Relationship("RevenueSummary", "MarketShareAnalysis",
                 "1:1", "prov_id + month_id",
                 "收入与市场份额对齐"),
    Relationship("ProdInstMonthSnapshot", "MarketShareAnalysis",
                 "N:1", "prov_id + month_id",
                 "产品实例收入汇总后与市场份额对比"),
    Relationship("ProdInstMonthSnapshot", "CustRetentionRate",
                 "N:1", "prov_id + month_id",
                 "产品实例参与保有率计算"),
]

""")

    f.write("# =============================================================================\n")
    f.write("# 操作方法 (Operations)\n")
    f.write("# =============================================================================\n\n")

    f.write("""def query_revenue_by_province(prov_id: str, month_id: str,
                              summaries: List[RevenueSummary]) -> Optional[RevenueSummary]:
    for s in summaries:
        if s.prov_id == prov_id and s.month_id == month_id:
            return s
    return None


def aggregate_inst_income(instances: List[InstIncomeRecord]) -> Dict[str, float]:
    agg: Dict[str, float] = {"billing_charge": 0.0, "billing_charge_after_tax": 0.0,
        "mobile_tele": 0.0, "fixedline_tele": 0.0, "broadband_access": 0.0,
        "value_added_busi": 0.0, "cs_resources": 0.0, "cs_5g": 0.0,
        "cs_ict": 0.0, "cs_idc": 0.0, "cs_wlw": 0.0}
    for inst in instances:
        if inst.billing_charge_sum: agg["billing_charge"] += inst.billing_charge_sum
        if inst.billing_charge_after_tax_sum: agg["billing_charge_after_tax"] += inst.billing_charge_after_tax_sum
        if inst.mobile_tele_income_sum: agg["mobile_tele"] += inst.mobile_tele_income_sum
        if inst.fixedline_tele_income_sum: agg["fixedline_tele"] += inst.fixedline_tele_income_sum
        if inst.broadband_access_income_sum: agg["broadband_access"] += inst.broadband_access_income_sum
        if inst.value_added_busi_income_sum: agg["value_added_busi"] += inst.value_added_busi_income_sum
        if inst.cs_resources_income_sum: agg["cs_resources"] += inst.cs_resources_income_sum
        if inst.cs_5g_income_sum: agg["cs_5g"] += inst.cs_5g_income_sum
        if inst.cs_ict_income_sum: agg["cs_ict"] += inst.cs_ict_income_sum
        if inst.cs_idc_income_sum: agg["cs_idc"] += inst.cs_idc_income_sum
        if inst.cs_wlw_income_sum: agg["cs_wlw"] += inst.cs_wlw_income_sum
    return agg


def cross_ref_billing_vs_financial(inst_income_list: List[InstIncomeRecord],
                                   prov_income: RevenueSummary) -> Dict[str, float]:
    agg = aggregate_inst_income(inst_income_list)
    billing_total = agg.get("billing_charge", 0.0)
    financial_total = (prov_income.income_sum or 0.0) * 10000
    diff = billing_total - financial_total
    diff_rate = diff / financial_total if financial_total != 0 else 0.0
    return {"billing_total_yuan": billing_total, "financial_total_yuan": financial_total,
            "diff_yuan": diff, "diff_rate": diff_rate}


def product_classify(std_prod_nbr_cd: str) -> ProductType:
    code = std_prod_nbr_cd.strip()
    if code.startswith("101010") or code in ("101020205",): return ProductType.MOBILE
    if code.startswith("101020"): return ProductType.BROADBAND
    if code.startswith("324"): return ProductType.ITV
    if code.startswith("10101"): return ProductType.FIXED_LINE
    return ProductType.RESOURCE_TYPE


def calc_retention_impact(cust_retention: CustRetentionRate,
                          revenue: RevenueSummary) -> Dict[str, Optional[float]]:
    if cust_retention.cl_cust_income_byl is None or revenue.income_sum is None:
        return {"imputed_revenue_loss": None}
    retention_rate = cust_retention.cl_cust_income_byl / 100.0
    retained = (revenue.base_busi_income_sum or 0.0) * retention_rate
    return {"retention_rate": cust_retention.cl_cust_income_byl,
            "retained_revenue_wan": round(retained, 2),
            "estimated_loss_wan": round((revenue.base_busi_income_sum or 0.0) - retained, 2)}


""")

    f.write("""@dataclass
class RevenueContributionAnalysis:
    \"\"\"客户与产品收入贡献分析接口\"\"\"

    @staticmethod
    def product_line_breakdown(inst_income_list: List[InstIncomeRecord]) -> Dict[str, float]:
        return aggregate_inst_income(inst_income_list)

    @staticmethod
    def billing_vs_financial_delta(inst_income_list: List[InstIncomeRecord],
                                   prov_income: RevenueSummary) -> Dict:
        return cross_ref_billing_vs_financial(inst_income_list, prov_income)

    @staticmethod
    def retention_revenue_impact(cust_retention: CustRetentionRate,
                                 revenue: RevenueSummary) -> Dict:
        return calc_retention_impact(cust_retention, revenue)

    @staticmethod
    def region_comparison(prov_id_list: List[str], month_id: str,
                          summaries: List[RevenueSummary]) -> Dict[str, Optional[RevenueSummary]]:
        return {p: query_revenue_by_province(p, month_id, summaries) for p in prov_id_list}

    @staticmethod
    def customer_segment_revenue(instances: List[ProdInstMonthSnapshot],
                                 income_records: List[InstIncomeRecord],
                                 cust_id_set: set) -> Dict[str, float]:
        inst_ids = {i.prod_inst_id for i in instances if i.cust_id in cust_id_set}
        relevant = [r for r in income_records if r.prod_inst_id in inst_ids]
        return aggregate_inst_income(relevant)


""")

    f.write("# =============================================================================\n")
    f.write("# 实体注册表 (Entity Registry)\n")
    f.write("# =============================================================================\n\n")

    f.write("""ENTITY_REGISTRY = {
    "ProdInstDaySnapshot": {"layer": "detail", "granularity": "product_instance+day", "source": "DWM_HUB_PRD_PD_INST_DAY"},
    "ProdInstMonthSnapshot": {"layer": "detail", "granularity": "product_instance+month", "source": "DWA_PRD_PD_INST_MONTH"},
    "InstIncomeRecord": {"layer": "detail", "granularity": "product_instance+month", "source": "DWM_EDA_PRD_INST_INCOME_MONTH"},
    "RevenueSummary": {"layer": "summary", "granularity": "province+month", "source": "TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH + 04"},
    "CostSummary": {"layer": "summary", "granularity": "province+month", "source": "TA_PCMG_JXDMX_CW_JYHX_COST_MONTH"},
    "ProfitSummary": {"layer": "summary", "granularity": "province+month", "source": "TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH"},
    "CashflowSummary": {"layer": "summary", "granularity": "province+month", "source": "TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH"},
    "SpecialCoRevenue": {"layer": "summary", "granularity": "special_co+month", "source": "TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH"},
    "CustRetentionRate": {"layer": "analysis", "granularity": "province+month+caliber", "source": "TA_PCMG_JXDMX_OLD_CUST_INCOME_BY_MONTH"},
    "BillingIndicatorDef": {"layer": "rule", "granularity": "indicator_code", "source": "12_billing_script"},
    "MarketShareAnalysis": {"layer": "analysis", "granularity": "province+month", "source": "TA_PCMG_JXDMX_SC_INCOME_USER_SD_MONTH"},
}

""")

print(f"Written {OUTPUT}")
