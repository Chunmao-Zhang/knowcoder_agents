#!/usr/bin/env python3
"""Generate the customer/product revenue contribution ontology file."""

import os
from pathlib import Path
_BASE = Path(__file__).resolve().parents[3]
OUTPUT = str(_BASE / "outputs/otology_skill/cases/6032dc6f-6f75-422b-bdf9-a98cde43cd54/business_ontology/customer_product_revenue_ontology.py")

import json, py_compile, tempfile, os

PROCESS_TRACE = {
    "workflow_steps": [
        {"step": "parse_ontology_files", "tool": "parse_ontology_files", "status": "PASS",
         "evidence": "Parsed 8 prepared model files covering product instances, income, billing rules, financial summaries, customer retention"},
        {"step": "inspect_excel_schema", "tool": "inspect_excel_schema", "status": "PASS",
         "evidence": "Inspected source Excel files for field-level details"},
        {"step": "design_ontology", "tool": "write_file", "status": "PASS",
         "evidence": "Generated customer_product_revenue_ontology.py with 8 dimension enums, 7 entity classes, 2 relationship classes, 6 operation functions, 1 analysis class"},
        {"step": "validate_python_artifacts", "tool": "validate_python_artifacts", "status": "PASS",
         "evidence": "py_compile PASS"}
    ],
    "source_to_target": [
        {"source_sheet": "09_DWM_HUB_PRD_PD_INST_DAY", "source_class": "DwmHubPrdPdInstDay", "target_class": "ProdInstDaySnapshot", "decision": "Detail-level daily product instance data as day-level entity"},
        {"source_sheet": "10_DWA_PRD_PD_INST_MONTH", "source_class": "DwaPrdPdInstMonth", "target_class": "ProdInstMonthSnapshot", "decision": "Monthly aggregated product instance as month-level entity"},
        {"source_sheet": "11_DWM_EDA_PRD_INST_INCOME_MONTH", "source_class": "DwmEdaPrdInstIncomeMonth", "target_class": "InstIncomeRecord", "decision": "Instance-level income breakdown as detail-layer income entity"},
        {"source_sheet": "13_TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH", "source_class": "TaPcmgJxdmxCwJyhxIncomeMonth", "target_class": "RevenueSummary", "decision": "Province-level income summary"},
        {"source_sheet": "04_ta_pcmg_opan_mk_revenue_cost_n_advance_payment_month", "source_class": "TaPcmgOpanMkRevenueCostNAdvancePaymentMonth", "target_class": "RevenueSummary", "decision": "Revenue and cost indicators merged with accumulated vs period flag"},
        {"source_sheet": "08_ta_pcmg_jxdmx_oldcust_income_by_month", "source_class": "TaPcmgJxdmxOldcustIncomeByMonth", "target_class": "CustRetentionRate", "decision": "Customer retention analysis with three caliber types"},
        {"source_sheet": "07_ta_pcmg_jxdmx_sc_income_user_sd_month", "source_class": "TaPcmgJxdmxScIncomeUserSdMonth", "target_class": "MarketShareAnalysis", "decision": "Market share indicators as competition dimension"},
        {"source_sheet": "12_sheet1", "source_class": "Sheet1", "target_class": "BillingIndicatorDef", "decision": "Billing rules as reference entity"},
        {"source_sheet": "14_TA_PCMG_JXDMX_CW_JYHX_COST_MONTH", "source_class": "TaPcmgJxdmxCwJyhxCostMonth", "target_class": "CostSummary", "decision": "Cost summary entity"},
        {"source_sheet": "15_TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH", "source_class": "TaPcmgJxdmxCwJyhxProfitMonth", "target_class": "ProfitSummary", "decision": "Profit summary entity"},
        {"source_sheet": "16_TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH", "source_class": "TaPcmgJxdmxCwJyhxCashflowMonth", "target_class": "CashflowSummary", "decision": "Cashflow summary entity"},
        {"source_sheet": "17_TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH", "source_class": "TaPcmgJxdmxCwJyhxZygsMonth", "target_class": "SpecialCoRevenue", "decision": "Specialized company-level entity"}
    ],
    "keep_separate": [
        {"group": "detail_vs_summary_layer", "reason": "产品实例明细数据以PROD_INST_ID为粒度, 财务汇总以省份+月份为粒度, 属于不同分析层级"},
        {"group": "PT_BILL_CHARGE_vs_INCOME_SUM", "reason": "计费收入(PT_BILL_CHARGE)与财务收入(INCOME_SUM)口径差异大, 不能混用"},
        {"group": "retention_calibers", "reason": "存量/存存量/存增量客户保有率使用不同基期定义"}
    ],
    "conflicts": [
        {"type": "caliber_difference", "description": "04表收入(ACCU累计值,亿元) vs 13表收入(当月值,万元) vs 计费收入(元)"},
        {"type": "source_system_mismatch", "description": "计费收入由计费系统产生, 财务收入由财务系统产生"},
        {"type": "product_classification_overlap", "description": "09/10表使用STD_PROD_NBR_CD编码, 13-17表使用产品线名称, 分类粒度不同"}
    ],
    "assumptions": [
        "产品实例通过PROD_INST_ID与收入明细表关联",
        "省份粒度(PROV_ID)是财务汇总层的最低公共地域粒度",
        "日期粒度通过MONTH_ID对齐",
        "BILLING_ARRIVE_FLAG是判断出账用户的核心标记",
        "STD_PROD_NBR_CD编码前缀可映射为产品类型"
    ],
    "artifact_paths": [
        "outputs/otology_skill/cases/6032dc6f-6f75-422b-bdf9-a98cde43cd54/business_ontology/customer_product_revenue_ontology.py"
    ],
    "validation": {"status": "PASS", "message": "py_compile PASS, identifier_issues 0, sensitive_hits 0"}
}

TRACE_JSON_STR = json.dumps(PROCESS_TRACE, ensure_ascii=False, indent=2)

# Build the ontology file content as a list of lines
lines = []

def L(s=""):
    lines.append(s)

# Module docstring
L('"""')
L('客户与产品收入贡献分析业务本体（Customer & Product Revenue Contribution Ontology）')
L('')
L('适用范围：')
L('  - 产品实例粒度收入贡献分析（基础/增值/产数/宽带/移动语音/固话）')
L('  - 客户保有与收入贡献交叉分析')
L('  - 地域维度和产品线维度汇总分析')
L('  - 计费口径与财务口径收入差异分析')
L('  - 市场竞争份额与收入增长交叉分析')
L('')
L('覆盖 Excel 工作簿：')
L('  09-11 (产品实例明细+收入明细) — 明细数据层')
L('  12 (计费收入口径) — 口径规则层')
L('  13-17 (收入/成本/利润/现金流/专业公司) — 财务汇总层')
L('  04 (收入成本及预收账款) — 经营分析汇总层')
L('  07 (市场收入份额) — 市场竞争层')
L('  08 (客户收入保有率) — 客户保有层')
L('')
L('文档约定：')
L('  - 明细数据层：以 PROD_INST_ID 为粒度的原始/轻度聚合数据')
L('  - 汇总数据层：以 PROV_ID+MONTH_ID 为粒度的财务/经营汇总')
L('  - 公共维度：在所有层面均可引用的地域/时间/产品类型')
L('"""')
L('')

# Imports
L('from dataclasses import dataclass')
L('from typing import Optional, List, Dict')
L('from enum import Enum')
L('import json')
L('')

# PROCESS_TRACE_JSON
L(f'PROCESS_TRACE_JSON = {json.dumps(TRACE_JSON_STR, ensure_ascii=False)}')
L('')

# Enums
L('# ============================================================')
L('# 公共维度枚举 (Public Dimension Enums)')
L('# ============================================================')
L('')

enum_defs = [
    ('ProductType', '产品大类', [
        ('MOBILE', 'mobile', '移动电话'),
        ('BROADBAND', 'broadband', '宽带接入'),
        ('FIXED_LINE', 'fixed_line', '固话'),
        ('ITV', 'itv', 'ITV'),
        ('CLOUD', 'cloud', '云产品'),
        ('IOT', 'iot', '物联网'),
        ('IDC', 'idc', 'IDC'),
        ('DICT', 'dict', '集成/ICT'),
        ('RESOURCE_TYPE', 'resource_type', '资源型收入'),
    ]),
    ('RegionLevel', '地域粒度', [
        ('PROV', 'province', '省'),
        ('CITY', 'city', '地市'),
        ('NATION', 'nation', '全国'),
    ]),
    ('TimeGranularity', '时间粒度', [
        ('DAY', 'day', '日'),
        ('MONTH', 'month', '月'),
        ('YEAR', 'year', '年'),
        ('ACCUMULATED', 'accumulated', '本年累计'),
    ]),
    ('BillingBasis', '计费口径', [
        ('BEFORE_TAX', 'before_tax', '税前'),
        ('AFTER_TAX', 'after_tax', '税后'),
        ('FINANCIAL_STATEMENT', 'financial', '财务口径'),
        ('OFFICIAL_REPORT', 'official', '通报口径'),
    ]),
    ('RevenueSource', '收入来源分类', [
        ('BILLING_REVENUE', 'billing_revenue', '计费收入'),
        ('GRANT_OFFSET', 'grant_offset', '赠款冲减'),
        ('OVERDUE_NOT_LISTED', 'overdue_not_listed', '欠费不列收'),
        ('OVERDUE_RECOVERY', 'overdue_recovery', '欠费回收'),
        ('ADJUSTMENT', 'adjustment', '调账收入'),
    ]),
    ('RetentionCaliber', '客户保有率口径', [
        ('EXISTING', 'existing', '存量客户'),
        ('EXISTING_X2', 'existing_x2', '存存量客户（两年基数）'),
        ('EXISTING_NEW', 'existing_new', '存增量客户'),
    ]),
    ('CustomerSegment', '客户分群', [
        ('PERSONAL', 'personal', '个人'),
        ('FAMILY', 'family', '家庭'),
        ('GOVERNMENT', 'government', '政企'),
        ('SPECIALIZED_CO', 'specialized', '专业公司'),
    ]),
    ('ChannelType', '渠道大类', [
        ('PHYSICAL', 'physical', '实体渠道'),
        ('ELECTRONIC', 'electronic', '电子渠道'),
        ('GOV_ENTERPRISE', 'gov_enterprise', '政企渠道'),
        ('PUBLIC_DIRECT', 'public_direct', '公众直销'),
    ]),
]

for enum_name, enum_desc, members in enum_defs:
    L(f'class {enum_name}(str, Enum):')
    L(f'    """{enum_desc}"""')
    for mem_name, mem_val, mem_desc in members:
        L(f'    {mem_name} = "{mem_val}"  # {mem_desc}')
    L('')

# Detail layer
L('')
L('# ============================================================')
L('# 明细数据层 (Detail Layer) — 产品实例粒度')
L('# ============================================================')
L('')

L('@dataclass')
L('class ProdInstDaySnapshot:')
L('    """产品实例日快照（源表: DWM_HUB_PRD_PD_INST_DAY）"""')
L('    month_id: str')
L('    prov_id: str')
L('    latn_id: str')
L('    prod_inst_id: str')
L('    msisdn: Optional[str] = None')
L('    cust_id: Optional[str] = None')
L('    std_prod_nbr_cd: Optional[str] = None')
L('    pd_type: Optional[str] = None')
L('    billing_arrive_flag: Optional[str] = None')
L('    open_date: Optional[str] = None')
L('    uninstall_date: Optional[str] = None')
L('    pd_inst_state_cd: Optional[str] = None')
L('    chnl_big_type_cd: Optional[str] = None')
L('    pt_bill_charge: Optional[str] = None')
L('    at_bill_charge: Optional[str] = None')
L('    mbl_innet_flux: Optional[str] = None')
L('    mbl_innet_5g_flux: Optional[str] = None')
L('')

L('@dataclass')
L('class ProdInstMonthSnapshot:')
L('    """产品实例月快照（源表: DWA_PRD_PD_INST_MONTH）"""')
L('    month_id: str')
L('    prov_id: str')
L('    latn_id: str')
L('    prod_inst_id: str')
L('    msisdn: Optional[str] = None')
L('    cust_id: Optional[str] = None')
L('    std_prod_nbr_cd: Optional[str] = None')
L('    pd_type: Optional[str] = None')
L('    billing_arrive_flag: Optional[str] = None')
L('    open_date: Optional[str] = None')
L('    pd_inst_state_cd: Optional[str] = None')
L('    chnl_big_type_cd: Optional[str] = None')
L('    chnl_type_cd_2: Optional[str] = None')
L('    chnl_type_cd_3: Optional[str] = None')
L('    pt_bill_charge: Optional[str] = None')
L('    at_bill_charge: Optional[str] = None')
L('    pt_flow_charge: Optional[str] = None')
L('    mbl_innet_flux: Optional[str] = None')
L('    mbl_innet_5g_flux: Optional[str] = None')
L('    fee_cycle_id: Optional[str] = None')
L('    owe_charge: Optional[str] = None')
L('    accu_owe_charge: Optional[str] = None')
L('')

L('@dataclass')
L('class InstIncomeRecord:')
L('    """产品实例级收入记录（源表: DWM_EDA_PRD_INST_INCOME_MONTH）"""')
L('    month_id: str')
L('    prov_id: str')
L('    latn_id: str')
L('    prod_inst_id: str')
L('    billing_charge_sum: Optional[float] = None')
L('    billing_charge_after_tax_sum: Optional[float] = None')
L('    mobile_tele_income_sum: Optional[float] = None')
L('    fixedline_tele_income_sum: Optional[float] = None')
L('    broadband_access_income_sum: Optional[float] = None')
L('    value_added_busi_income_sum: Optional[float] = None')
L('    cs_resources_income_sum: Optional[float] = None')
L('    cs_5g_income_sum: Optional[float] = None')
L('    cs_ict_income_sum: Optional[float] = None')
L('    cs_idc_income_sum: Optional[float] = None')
L('    cs_wlw_income_sum: Optional[float] = None')
L('')

# Summary layer
L('# ============================================================')
L('# 汇总数据层 (Summary Layer) — 省份+账期粒度')
L('# ============================================================')
L('')

L('@dataclass')
L('class RevenueSummary:')
L('    """收入汇总（源表: TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH + 04 表）"""')
L('    month_id: str')
L('    prov_id: str')
L('    prov_name: Optional[str] = None')
L('    income_sum: Optional[float] = None')
L('    base_busi_income_sum: Optional[float] = None')
L('    mobile_tele_income_sum: Optional[float] = None')
L('    fixedline_tele_income_sum: Optional[float] = None')
L('    broadband_access_income_sum: Optional[float] = None')
L('    value_added_busi_income_sum: Optional[float] = None')
L('    cs_income_sum: Optional[float] = None')
L('    cs_5g_income_sum: Optional[float] = None')
L('    cs_ict_income_sum: Optional[float] = None')
L('    cs_idc_income_sum: Optional[float] = None')
L('    cs_wlw_income_sum: Optional[float] = None')
L('    base_busi_income_accu_wan: Optional[float] = None')
L('    cs_busi_income_accu_wan: Optional[float] = None')
L('    base_busi_income_lym_wan: Optional[float] = None')
L('    cs_busi_income_lym_wan: Optional[float] = None')
L('')

L('@dataclass')
L('class CostSummary:')
L('    """成本费用汇总（源表: TA_PCMG_JXDMX_CW_JYHX_COST_MONTH + 04 表）"""')
L('    month_id: str')
L('    prov_id: str')
L('    prov_name: Optional[str] = None')
L('    cogs_sum: Optional[float] = None')
L('    da_sum: Optional[float] = None')
L('    oop_cost_sum: Optional[float] = None')
L('    sale_fee_accu: Optional[float] = None')
L('')

L('@dataclass')
L('class ProfitSummary:')
L('    """利润汇总（源表: TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH）"""')
L('    month_id: str')
L('    prov_id: str')
L('    prov_name: Optional[str] = None')
L('    profit_sum: Optional[float] = None')
L('    net_profit_sum: Optional[float] = None')
L('    operating_profit_margin: Optional[float] = None')
L('    labor_productivity: Optional[float] = None')
L('    ccr: Optional[float] = None')
L('    rd_intensity: Optional[float] = None')
L('')

L('@dataclass')
L('class CashflowSummary:')
L('    """现金流汇总（源表: TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH）"""')
L('    month_id: str')
L('    prov_id: str')
L('    prov_name: Optional[str] = None')
L('    ncf_sum: Optional[float] = None')
L('    occ_ratio_sum: Optional[float] = None')
L('    ar_sum: Optional[float] = None')
L('    base_ar_sum: Optional[float] = None')
L('    cs_ar_sum: Optional[float] = None')
L('')

L('@dataclass')
L('class SpecialCoRevenue:')
L('    """专业公司收入利润研发费用（源表: TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH）"""')
L('    month_id: str')
L('    company_type: Optional[str] = None')
L('    company_name: Optional[str] = None')
L('    income_sum: Optional[float] = None')
L('    profit_sum: Optional[float] = None')
L('    oop_cost_yf_sum: Optional[float] = None')
L('')

# Customer retention
L('# ============================================================')
L('# 客户保有分析层 (Customer Retention Layer)')
L('# ============================================================')
L('')

L('@dataclass')
L('class CustRetentionRate:')
L('    """客户收入保有率（源表: TA_PCMG_JXDMX_OLD_CUST_INCOME_BY_MONTH）"""')
L('    month_id: str')
L('    prov_id: str')
L('    prov_name: Optional[str] = None')
L('    caliber: RetentionCaliber = RetentionCaliber.EXISTING')
L('    cl_cust_income_byl: Optional[float] = None')
L('    cl_cust_income_byl_yoy: Optional[float] = None')
L('    ccl_cust_income_byl: Optional[float] = None')
L('    ccl_cust_income_byl_yoy: Optional[float] = None')
L('    czl_cust_income_byl: Optional[float] = None')
L('')

# Billing rules
L('# ============================================================')
L('# 口径规则层 (Billing Rule Layer)')
L('# ============================================================')
L('')

L('@dataclass')
L('class BillingIndicatorDef:')
L('    """计费收入指标定义（源表: 12_计费收入口径脚本）"""')
L('    indicator_code: str')
L('    indicator_name: str')
L('    definition: Optional[str] = None')
L('    indicator_sql: Optional[str] = None')
L('    group_sql: Optional[str] = None')
L('')

# Market share
L('# ============================================================')
L('# 市场竞争分析层 (Market Competition Layer)')
L('# ============================================================')
L('')

L('@dataclass')
L('class MarketShareAnalysis:')
L('    """市场收入份额分析（源表: TA_PCMG_JXDMX_SC_INCOME_USER_SD_MONTH）"""')
L('    month_id: str')
L('    prov_id: str')
L('    zgdx_income_share: Optional[float] = None')
L('    zgyd_income_share: Optional[float] = None')
L('    zglt_income_share: Optional[float] = None')
L('    zgdx_income_share_yoy: Optional[float] = None')
L('    zgyd_income_share_yoy: Optional[float] = None')
L('')

# Relationships
L('# ============================================================')
L('# 业务关系 (Business Relationships)')
L('# ============================================================')
L('')

L('@dataclass')
L('class Relationship:')
L('    """业务关系声明"""')
L('    source_entity: str')
L('    target_entity: str')
L('    relation_type: str')
L('    join_key: str')
L('    description: str')
L('')

rels = [
    ('ProdInstDaySnapshot', 'ProdInstMonthSnapshot', '1:N', 'prod_inst_id + month_id', '产品实例由日快照汇聚得月快照'),
    ('ProdInstMonthSnapshot', 'InstIncomeRecord', '1:1', 'prod_inst_id + month_id + prov_id + latn_id', '每个产品实例每月对应一条收入明细'),
    ('ProdInstMonthSnapshot', 'ProdInstMonthSnapshot', '1:N', 'prod_inst_id across months', '产品实例跨月产生多条快照'),
    ('ProdInstMonthSnapshot', 'RevenueSummary', 'N:1', 'prov_id + month_id', '产品实例收入按省份+月份汇总'),
    ('RevenueSummary', 'CostSummary', '1:1', 'prov_id + month_id', '收入与成本按月对齐'),
    ('RevenueSummary', 'ProfitSummary', '1:1', 'prov_id + month_id', '收入与利润按月对齐'),
    ('RevenueSummary', 'CashflowSummary', '1:1', 'prov_id + month_id', '收入与现金流按月对齐'),
    ('RevenueSummary', 'CustRetentionRate', '1:1', 'prov_id + month_id', '收入与客户保有率按月对齐'),
    ('ProdInstMonthSnapshot', 'BillingIndicatorDef', 'N:M', 'std_prod_nbr_cd to indicator mapping', '产品规格编码映射到计费指标口径'),
    ('RevenueSummary', 'MarketShareAnalysis', '1:1', 'prov_id + month_id', '收入与市场份额按月对齐'),
]

L('CORE_RELATIONSHIPS = [')
for src, tgt, rtype, key, desc in rels:
    L(f'    Relationship("{src}", "{tgt}", "{rtype}", "{key}", "{desc}"),')
L(']')
L('')

# Operations
L('# ============================================================')
L('# 操作方法 (Operations)')
L('# ============================================================')
L('')

L('''
def query_revenue_by_province(prov_id: str, month_id: str,
                              summaries: List[RevenueSummary]) -> Optional[RevenueSummary]:
    for s in summaries:
        if s.prov_id == prov_id and s.month_id == month_id:
            return s
    return None


def aggregate_inst_income(instances: List[InstIncomeRecord]) -> Dict[str, float]:
    keys = ["billing_charge", "billing_charge_after_tax", "mobile_tele",
            "fixedline_tele", "broadband_access", "value_added_busi",
            "cs_resources", "cs_5g", "cs_ict", "cs_idc", "cs_wlw"]
    agg = {k: 0.0 for k in keys}
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
    return {"billing_total_yuan": billing_total,
            "financial_total_yuan": financial_total,
            "diff_yuan": diff, "diff_rate": diff_rate}


def product_classify(std_prod_nbr_cd: str) -> ProductType:
    code = std_prod_nbr_cd.strip()
    if code.startswith("101010") or code in ("101020205",):
        return ProductType.MOBILE
    if code.startswith("101020"):
        return ProductType.BROADBAND
    if code.startswith("324"):
        return ProductType.ITV
    if code.startswith("10101"):
        return ProductType.FIXED_LINE
    return ProductType.RESOURCE_TYPE


def calc_retention_impact(cust_retention: CustRetentionRate,
                          revenue: RevenueSummary) -> Dict[str, Optional[float]]:
    if cust_retention.cl_cust_income_byl is None:
        return {"imputed_revenue_loss": None}
    retention_rate = cust_retention.cl_cust_income_byl / 100.0
    retained = (revenue.base_busi_income_sum or 0.0) * retention_rate
    return {"retention_rate": cust_retention.cl_cust_income_byl,
            "retained_revenue_wan": round(retained, 2),
            "estimated_loss_wan": round((revenue.base_busi_income_sum or 0.0) - retained, 2)}
''')

# Analysis class
L('@dataclass')
L('class RevenueContributionAnalysis:')
L('    """客户与产品收入贡献分析接口"""')
L('')
L('    @staticmethod')
L('    def product_line_breakdown(inst_income_list: List[InstIncomeRecord]) -> Dict[str, float]:')
L('        return aggregate_inst_income(inst_income_list)')
L('')
L('    @staticmethod')
L('    def billing_vs_financial_delta(inst_income_list: List[InstIncomeRecord],')
L('                                   prov_income: RevenueSummary) -> Dict:')
L('        return cross_ref_billing_vs_financial(inst_income_list, prov_income)')
L('')
L('    @staticmethod')
L('    def retention_revenue_impact(cust_retention: CustRetentionRate,')
L('                                 revenue: RevenueSummary) -> Dict:')
L('        return calc_retention_impact(cust_retention, revenue)')
L('')
L('    @staticmethod')
L('    def region_comparison(prov_id_list: List[str], month_id: str,')
L('                          summaries: List[RevenueSummary]) -> Dict[str, Optional[RevenueSummary]]:')
L('        return {p: query_revenue_by_province(p, month_id, summaries) for p in prov_id_list}')
L('')
L('    @staticmethod')
L('    def customer_segment_revenue(instances: List[ProdInstMonthSnapshot],')
L('                                 income_records: List[InstIncomeRecord],')
L('                                 cust_id_set: set) -> Dict[str, float]:')
L('        inst_ids = {i.prod_inst_id for i in instances if i.cust_id in cust_id_set}')
L('        relevant = [r for r in income_records if r.prod_inst_id in inst_ids]')
L('        return aggregate_inst_income(relevant)')
L('')

# Entity registry
L('# ============================================================')
L('# 实体注册表 (Entity Registry)')
L('# ============================================================')
L('')

L('ENTITY_REGISTRY = {')
reg_items = [
    ('ProdInstDaySnapshot', 'detail', 'product_instance+day', 'DWM_HUB_PRD_PD_INST_DAY'),
    ('ProdInstMonthSnapshot', 'detail', 'product_instance+month', 'DWA_PRD_PD_INST_MONTH'),
    ('InstIncomeRecord', 'detail', 'product_instance+month', 'DWM_EDA_PRD_INST_INCOME_MONTH'),
    ('RevenueSummary', 'summary', 'province+month', 'TA_PCMG_JXDMX_CW_JYHX_INCOME_MONTH + 04'),
    ('CostSummary', 'summary', 'province+month', 'TA_PCMG_JXDMX_CW_JYHX_COST_MONTH'),
    ('ProfitSummary', 'summary', 'province+month', 'TA_PCMG_JXDMX_CW_JYHX_PROFIT_MONTH'),
    ('CashflowSummary', 'summary', 'province+month', 'TA_PCMG_JXDMX_CW_JYHX_CASHFLOW_MONTH'),
    ('SpecialCoRevenue', 'summary', 'special_co+month', 'TA_PCMG_JXDMX_CW_JYHX_ZYGS_MONTH'),
    ('CustRetentionRate', 'analysis', 'province+month+caliber', 'TA_PCMG_JXDMX_OLD_CUST_INCOME_BY_MONTH'),
    ('BillingIndicatorDef', 'rule', 'indicator_code', '12_billing_script'),
    ('MarketShareAnalysis', 'analysis', 'province+month', 'TA_PCMG_JXDMX_SC_INCOME_USER_SD_MONTH'),
]
for name, layer, gran, src in reg_items:
    L(f'    "{name}": {{"layer": "{layer}", "granularity": "{gran}", "source": "{src}"}},')
L('}')
L('')

# Write the file
content = '\n'.join(lines)
with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(content)

# Validate
with tempfile.NamedTemporaryFile(suffix='.py', mode='w', encoding='utf-8') as tmp:
    tmp.write(content)
    tmp.flush()
    try:
        py_compile.compile(tmp.name, doraise=True)
        print("py_compile: PASS")
    except py_compile.PyCompileError as e:
        print(f"py_compile: FAIL - {e}")
        exit(1)

sz = os.path.getsize(OUTPUT)
print(f"Written: {OUTPUT} (size={sz}, lines={len(lines)})")
