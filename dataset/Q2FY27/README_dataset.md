# Q2 FY27 synthetic dataset

Two independent schemes, one quarter (1 Jul - 30 Sep 2026). All names, registration numbers and people are fictional. The feeder sleeve is not in this dataset.

Generated with `python -m generator --seed 20260930`. 160 source files.

| File | Normally produced by | Consumed by (UI page) | Feeds tables |
|---|---|---|---|
| `scheme_A_gift/AML_Policy_Extract.pdf` | FME compliance | KYC / AML / FATCA | evidence |
| `scheme_A_gift/CCD_Subscription_Summary_I-A2.pdf` | Fund counsel | Deals, CPs & filings | instrument |
| `scheme_A_gift/CP_Checklist_I-A1_T2.xlsx` | Investment team / legal | Deals, CPs & filings | cp_item |
| `scheme_A_gift/CapitalCall_CG3_Allocation.xlsx` | FME finance (maker) / checker | Capital calls | capital_call, call_allocation |
| `scheme_A_gift/CapitalCall_CG3_Notice_Al_Nahda_Sovereign_Holdings.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_A_gift/CapitalCall_CG3_Notice_FME_Contribution.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_A_gift/CapitalCall_CG3_Notice_Nishi-Tokyo_Trust_Bank.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_A_gift/CapitalCall_CG3_Notice_Sakura_Residential_Holdings.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_A_gift/Charge_Filing_CHG9_I-A1.pdf` | ROC / company secretary of the SPV | Deals, CPs & filings | charge_filing, evidence |
| `scheme_A_gift/Covenant_Certificate_SPV-A1_30Sep26.pdf` | Developer CFO (Kalpavriksha Realty) | Project monitoring | covenant_test |
| `scheme_A_gift/Covenant_Certificate_SPV-A2_30Sep26.pdf` | Developer CFO (Greenfield Estates) | Project monitoring | covenant_test |
| `scheme_A_gift/DTD_Summary_I-A1.pdf` | Fund counsel | Deals, CPs & filings | instrument |
| `scheme_A_gift/Deal_Master_SchemeA.xlsx` | Investment team | Instruments & accruals / Deals, CPs & filings | project_spv, instrument, tranche, covenant_test |
| `scheme_A_gift/Demat_Holding_Statement_SchemeA_30Sep26.pdf` | Custodian / DP | Bank & custody reconciliation | custody_account, custody_holding |
| `scheme_A_gift/Demat_Transaction_Statement_SchemeA_Jul-Sep26.csv` | Custodian / DP | Bank & custody reconciliation | custody_txn |
| `scheme_A_gift/Developer_MIS_SPV-A1_Aug26.xlsx` | Developer (Kalpavriksha Realty) | Project monitoring | mis_month |
| `scheme_A_gift/Developer_MIS_SPV-A1_Jul26.xlsx` | Developer (Kalpavriksha Realty) | Project monitoring | mis_month |
| `scheme_A_gift/Developer_MIS_SPV-A1_Sep26.xlsx` | Developer (Kalpavriksha Realty) | Project monitoring | mis_month |
| `scheme_A_gift/Developer_MIS_SPV-A2_Aug26.xlsx` | Developer (Greenfield Estates) | Project monitoring | mis_month |
| `scheme_A_gift/Developer_MIS_SPV-A2_Jul26.xlsx` | Developer (Greenfield Estates) | Project monitoring | mis_month |
| `scheme_A_gift/Developer_MIS_SPV-A2_Sep26.xlsx` | Developer (Greenfield Estates) | Project monitoring | mis_month |
| `scheme_A_gift/Distribution_DA1_Notice_Al_Nahda_Sovereign_Holdings.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_A_gift/Distribution_DA1_Notice_FME_Contribution.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_A_gift/Distribution_DA1_Notice_Nishi-Tokyo_Trust_Bank.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_A_gift/Distribution_DA1_Notice_Sakura_Residential_Holdings.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_A_gift/Distribution_DA1_PaymentFile.csv` | FME finance - IBU bulk-payment upload | Distributions | distribution_line |
| `scheme_A_gift/Distribution_DA1_Schedule.xlsx` | FME finance (maker) / checker | Distributions | distribution, distribution_line, wht_entry |
| `scheme_A_gift/Evidence/Annual_Report_FY26_Filing_Ack.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_A_gift/Evidence/Compliance_Report_FY26_Filing_Ack.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_A_gift/Evidence/Form61B_CY2025_Filing_Ack.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_A_gift/Evidence/ICSI_Certification_Completion.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_A_gift/Evidence/IFSCA_Q2FY27_Submission_Ack.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_A_gift/Evidence/Valuation_Dispatch_Confirmation_30Sep26.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_A_gift/FCGPR_Acknowledgement_I-A1_T2.pdf` | AD bank / RBI reporting portal | Deals, CPs & filings | fema_filing, evidence |
| `scheme_A_gift/FINGate_Registration_Evidence.pdf` | FIU-IND portal | KYC / AML / FATCA | evidence |
| `scheme_A_gift/FME_Fee_Invoice_Q1FY27.pdf` | FME / investment manager | Quarter close & NAV | journal |
| `scheme_A_gift/FME_Fee_Invoice_Q2FY27.pdf` | FME / investment manager | Quarter close & NAV | journal |
| `scheme_A_gift/FX_Rates_USDINR_Daily_Jul-Sep26.csv` | Rate feed (FBIL-style) | FX & translation | fx_rate |
| `scheme_A_gift/IBU_Statement_SchemeA_USD_Jul-Sep26.csv` | Bank (IBU) - CSV download | Ingestion / Bank reconciliation | bank_account, bank_line |
| `scheme_A_gift/IBU_Statement_SchemeA_USD_Jul-Sep26.mt940` | Bank (IBU) - SWIFT MT940 | Ingestion / Bank reconciliation | bank_account, bank_line |
| `scheme_A_gift/IBU_Statement_SchemeA_USD_Jul-Sep26.pdf` | Bank (IBU) | Bank & custody reconciliation | bank_account, bank_line |
| `scheme_A_gift/IFSCA_Compliance_Calendar_SchemeA.xlsx` | FME compliance | Calendar / Exceptions | obligation, evidence |
| `scheme_A_gift/IFSCA_Q1FY27_Submission_Email.pdf` | FME compliance mailbox | Calendar | evidence |
| `scheme_A_gift/IFSCA_Quarterly_Report_Q1FY27_as_filed.xlsx` | FME compliance (prior filing) | Report centre | report_run |
| `scheme_A_gift/Investor_Register_SchemeA.xlsx` | Fund administrator / RTA | Investors & commitments | investor, commitment, unit_class |
| `scheme_A_gift/KYC_Pack_Al_Nahda_Sovereign_Holdings/BO_declaration.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_A_gift/KYC_Pack_Al_Nahda_Sovereign_Holdings/CRS_self_certification.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_A_gift/KYC_Pack_Al_Nahda_Sovereign_Holdings/FATCA_W8BENE_summary.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_A_gift/KYC_Pack_Al_Nahda_Sovereign_Holdings/checklist.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_A_gift/KYC_Pack_Al_Nahda_Sovereign_Holdings/screening_report.pdf` | Screening vendor | KYC / AML / FATCA | kyc_document, evidence, screening_log |
| `scheme_A_gift/KYC_Pack_Nishi-Tokyo_Trust_Bank/BO_declaration.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_A_gift/KYC_Pack_Nishi-Tokyo_Trust_Bank/CRS_self_certification.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_A_gift/KYC_Pack_Nishi-Tokyo_Trust_Bank/FATCA_W8BENE_summary.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_A_gift/KYC_Pack_Nishi-Tokyo_Trust_Bank/checklist.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_A_gift/KYC_Pack_Nishi-Tokyo_Trust_Bank/screening_report.pdf` | Screening vendor | KYC / AML / FATCA | kyc_document, evidence, screening_log |
| `scheme_A_gift/KYC_Pack_Sakura_Residential_Holdings/BO_declaration.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_A_gift/KYC_Pack_Sakura_Residential_Holdings/CRS_self_certification.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_A_gift/KYC_Pack_Sakura_Residential_Holdings/FATCA_W8BENE_summary.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_A_gift/KYC_Pack_Sakura_Residential_Holdings/checklist.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_A_gift/KYC_Pack_Sakura_Residential_Holdings/screening_report.pdf` | Screening vendor | KYC / AML / FATCA | kyc_document, evidence, screening_log |
| `scheme_A_gift/KYC_Register_SchemeA.xlsx` | FME compliance (AML PO) | KYC / AML / FATCA | kyc_file, kyc_document, screening_log, fatca_crs |
| `scheme_A_gift/PPM_Term_Sheet_SchemeA.pdf` | FME / fund counsel | Investors & commitments | scheme, scheme_term |
| `scheme_A_gift/Pricing_Certificate_I-A1_T2.pdf` | Chartered accountant | Deals, CPs & filings | evidence |
| `scheme_A_gift/Side_Letter_Summary_SchemeA.xlsx` | Fund counsel / IR | Investors & commitments | side_letter_term |
| `scheme_A_gift/Tally_SchemeA_DayBook_Q2FY27.xml` | Client finance team (Tally export) | Tally bridge | tally_voucher |
| `scheme_A_gift/Tally_SchemeA_LedgerMasters.xlsx` | Client finance team (Tally export) | Tally bridge | tally_ledger_balance, gl_account |
| `scheme_A_gift/Tally_SchemeA_TrialBalance_30Sep26.xlsx` | Client finance team (Tally export) | Tally bridge | tally_ledger_balance |
| `scheme_A_gift/Tranche2_Disbursement_Advice_I-A1.pdf` | FME finance | Deals, CPs & filings | tranche |
| `scheme_A_gift/Unit_Register_SchemeA.xlsx` | Fund administrator / RTA | Capital accounts | unit_ledger |
| `scheme_A_gift/Valuation_Inputs_SchemeA_30Sep26.xlsx` | Independent registered valuer | Valuation | valuation_item |
| `scheme_A_gift/Valuation_Report_SchemeA_30Sep26.pdf` | Independent registered valuer | Valuation | valuation_cycle, valuation_item |
| `scheme_A_gift/Vendor_Invoices_Q2FY27/Administrator_Q1FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_A_gift/Vendor_Invoices_Q2FY27/Administrator_Q2FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_A_gift/Vendor_Invoices_Q2FY27/Audit_Q2FY27_AccrualNote.pdf` | Fund accounting | Quarter close & NAV | journal |
| `scheme_A_gift/Vendor_Invoices_Q2FY27/Legal_Q1FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_A_gift/Vendor_Invoices_Q2FY27/Trustee_Q1FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_A_gift/Vendor_Invoices_Q2FY27/Trustee_Q2FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_A_gift/Vendor_Invoices_Q2FY27/Valuer_Q2FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_A_gift/WHT_Certificate_Al_Nahda_Sovereign_Holdings.pdf` | FME / deductor | Distributions | wht_entry |
| `scheme_A_gift/WHT_Certificate_Nishi-Tokyo_Trust_Bank.pdf` | FME / deductor | Distributions | wht_entry |
| `scheme_A_gift/WHT_Certificate_Sakura_Residential_Holdings.pdf` | FME / deductor | Distributions | wht_entry |
| `scheme_A_gift/WHT_Deposit_Challan_DA1.pdf` | Authorised bank / tax portal | Distributions | wht_entry, evidence |
| `scheme_B_onshore/Bank_Statement_SchemeB_INR_Jul-Sep26.pdf` | Bank | Bank & custody reconciliation | bank_account, bank_line |
| `scheme_B_onshore/Bank_Statement_SchemeB_INR_Jul-Sep26.xls` | Bank - XLS download | Ingestion / Bank reconciliation | bank_account, bank_line |
| `scheme_B_onshore/CP_Checklist_I-B1_T2.xlsx` | Investment team / legal | Deals, CPs & filings | cp_item |
| `scheme_B_onshore/CTR_FY26_extract.pdf` | FME compliance | Calendar | evidence |
| `scheme_B_onshore/CapitalCall_CB3_Allocation.xlsx` | FME finance (maker) / checker | Capital calls | capital_call, call_allocation |
| `scheme_B_onshore/CapitalCall_CB3_Notice_Rao_Family_Office.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_B_onshore/CapitalCall_CB3_Notice_Sahyadri_Cooperative_Bank.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_B_onshore/CapitalCall_CB3_Notice_Sponsor_Commitment.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_B_onshore/CapitalCall_CB3_Notice_Vindhya_Life_Insurance.pdf` | FME / fund administrator | Capital calls | capital_call, call_allocation |
| `scheme_B_onshore/Charge_Filing_CHG9_I-B1.pdf` | ROC / company secretary of the SPV | Deals, CPs & filings | charge_filing, evidence |
| `scheme_B_onshore/Covenant_Certificate_SPV-B1_30Sep26.pdf` | Developer CFO (Urban Homes Group) | Project monitoring | covenant_test |
| `scheme_B_onshore/Covenant_Certificate_SPV-B2_30Sep26.pdf` | Developer CFO (Skyline Projects) | Project monitoring | covenant_test |
| `scheme_B_onshore/DTD_Summary_I-B1.pdf` | Fund counsel | Deals, CPs & filings | instrument |
| `scheme_B_onshore/DTD_Summary_I-B2.pdf` | Fund counsel | Deals, CPs & filings | instrument |
| `scheme_B_onshore/Deal_Master_SchemeB.xlsx` | Investment team | Instruments & accruals / Deals, CPs & filings | project_spv, instrument, tranche, covenant_test |
| `scheme_B_onshore/Demat_Holding_Statement_SchemeB_30Sep26.pdf` | Custodian / DP | Bank & custody reconciliation | custody_account, custody_holding |
| `scheme_B_onshore/Demat_Transaction_Statement_SchemeB_Jul-Sep26.csv` | Custodian / DP | Bank & custody reconciliation | custody_txn |
| `scheme_B_onshore/Developer_MIS_SPV-B1_Aug26.xlsx` | Developer (Urban Homes Group) | Project monitoring | mis_month |
| `scheme_B_onshore/Developer_MIS_SPV-B1_Jul26.xlsx` | Developer (Urban Homes Group) | Project monitoring | mis_month |
| `scheme_B_onshore/Developer_MIS_SPV-B1_Sep26.xlsx` | Developer (Urban Homes Group) | Project monitoring | mis_month |
| `scheme_B_onshore/Developer_MIS_SPV-B2_Aug26.xlsx` | Developer (Skyline Projects) | Project monitoring | mis_month |
| `scheme_B_onshore/Developer_MIS_SPV-B2_Jul26.xlsx` | Developer (Skyline Projects) | Project monitoring | mis_month |
| `scheme_B_onshore/Developer_MIS_SPV-B2_Sep26.xlsx` | Developer (Skyline Projects) | Project monitoring | mis_month |
| `scheme_B_onshore/Distribution_DB1_Notice_Rao_Family_Office.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_B_onshore/Distribution_DB1_Notice_Sahyadri_Cooperative_Bank.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_B_onshore/Distribution_DB1_Notice_Sponsor_Commitment.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_B_onshore/Distribution_DB1_Notice_Vindhya_Life_Insurance.pdf` | FME / fund administrator | Distributions | distribution, distribution_line |
| `scheme_B_onshore/Distribution_DB1_Schedule.xlsx` | FME finance (maker) / checker | Distributions | distribution, distribution_line, wht_entry |
| `scheme_B_onshore/Evidence/Form64C_64D_FY26_Filing_Ack.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_B_onshore/Evidence/PPM_Audit_FY26_Filing_Ack.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_B_onshore/Evidence/SEBI_QAR_Q2FY27_Submission_Ack.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_B_onshore/Evidence/Valuation_Dispatch_Confirmation_30Sep26.pdf` | Regulator portal / mailbox | Calendar | evidence |
| `scheme_B_onshore/FATCA_CRS_SelfCert_Rao_Family_Office.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_B_onshore/FATCA_CRS_SelfCert_Sahyadri_Cooperative_Bank.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_B_onshore/FATCA_CRS_SelfCert_Vindhya_Life_Insurance.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence, fatca_crs |
| `scheme_B_onshore/Form16A_Rao_Family_Office.pdf` | FME / deductor | Distributions | wht_entry |
| `scheme_B_onshore/Form16A_Sahyadri_Cooperative_Bank.pdf` | FME / deductor | Distributions | wht_entry |
| `scheme_B_onshore/Form16A_Vindhya_Life_Insurance.pdf` | FME / deductor | Distributions | wht_entry |
| `scheme_B_onshore/Form64C_Statement_Rao_Family_Office.pdf` | FME tax team (draft) | Report centre | distribution_line, report_run |
| `scheme_B_onshore/Form64C_Statement_Sahyadri_Cooperative_Bank.pdf` | FME tax team (draft) | Report centre | distribution_line, report_run |
| `scheme_B_onshore/Form64C_Statement_Sponsor_Commitment.pdf` | FME tax team (draft) | Report centre | distribution_line, report_run |
| `scheme_B_onshore/Form64C_Statement_Vindhya_Life_Insurance.pdf` | FME tax team (draft) | Report centre | distribution_line, report_run |
| `scheme_B_onshore/IM_Fee_Invoice_Q1FY27.pdf` | FME / investment manager | Quarter close & NAV | journal |
| `scheme_B_onshore/IM_Fee_Invoice_Q2FY27.pdf` | FME / investment manager | Quarter close & NAV | journal |
| `scheme_B_onshore/Investor_Register_SchemeB.xlsx` | Fund administrator / RTA | Investors & commitments | investor, commitment, unit_class, side_letter_term |
| `scheme_B_onshore/KYC_Pack_Rao_Family_Office/BO_declaration.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Rao_Family_Office/CKYC_record.pdf` | CKYC registry | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Rao_Family_Office/NetWorth_Certificate.pdf` | Chartered accountant | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Rao_Family_Office/checklist.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Rao_Family_Office/screening_report.pdf` | Screening vendor | KYC / AML / FATCA | kyc_document, evidence, screening_log |
| `scheme_B_onshore/KYC_Pack_Sahyadri_Cooperative_Bank/BO_declaration.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Sahyadri_Cooperative_Bank/CKYC_record.pdf` | CKYC registry | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Sahyadri_Cooperative_Bank/checklist.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Sahyadri_Cooperative_Bank/screening_report.pdf` | Screening vendor | KYC / AML / FATCA | kyc_document, evidence, screening_log |
| `scheme_B_onshore/KYC_Pack_Vindhya_Life_Insurance/BO_declaration.pdf` | Investor | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Vindhya_Life_Insurance/CKYC_record.pdf` | CKYC registry | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Vindhya_Life_Insurance/checklist.pdf` | FME compliance | KYC / AML / FATCA | kyc_document, evidence |
| `scheme_B_onshore/KYC_Pack_Vindhya_Life_Insurance/screening_report.pdf` | Screening vendor | KYC / AML / FATCA | kyc_document, evidence, screening_log |
| `scheme_B_onshore/KYC_Register_SchemeB.xlsx` | FME compliance (AML PO) | KYC / AML / FATCA | kyc_file, kyc_document, screening_log, fatca_crs |
| `scheme_B_onshore/PPM_Term_Sheet_SchemeB.pdf` | FME / fund counsel | Investors & commitments | scheme, scheme_term |
| `scheme_B_onshore/SEBI_Compliance_Calendar_SchemeB.xlsx` | FME compliance | Calendar / Exceptions | obligation, evidence |
| `scheme_B_onshore/SEBI_Quarterly_Activity_Report_Q1FY27_as_filed.xlsx` | FME compliance (prior filing) | Report centre | report_run |
| `scheme_B_onshore/TDS_194LBB_Challan_DB1.pdf` | Authorised bank / tax portal | Distributions | wht_entry, evidence |
| `scheme_B_onshore/Tally_SchemeB_DayBook_Q2FY27.xml` | Client finance team (Tally export) | Tally bridge | tally_voucher |
| `scheme_B_onshore/Tally_SchemeB_LedgerMasters.xlsx` | Client finance team (Tally export) | Tally bridge | tally_ledger_balance, gl_account |
| `scheme_B_onshore/Tally_SchemeB_TrialBalance_30Sep26.xlsx` | Client finance team (Tally export) | Tally bridge | tally_ledger_balance |
| `scheme_B_onshore/Tranche2_Disbursement_Advice_I-B1.pdf` | FME finance | Deals, CPs & filings | tranche |
| `scheme_B_onshore/Unit_Register_SchemeB.xlsx` | Fund administrator / RTA | Capital accounts | unit_ledger |
| `scheme_B_onshore/Valuation_Inputs_SchemeB_30Sep26.xlsx` | Independent registered valuer | Valuation | valuation_item |
| `scheme_B_onshore/Valuation_Report_SchemeB_30Sep26.pdf` | Independent registered valuer | Valuation | valuation_cycle, valuation_item |
| `scheme_B_onshore/Vendor_Invoices_Q2FY27/Audit_Q2FY27_AccrualNote.pdf` | Fund accounting | Quarter close & NAV | journal |
| `scheme_B_onshore/Vendor_Invoices_Q2FY27/Legal_Q1FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_B_onshore/Vendor_Invoices_Q2FY27/Rta_Q1FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_B_onshore/Vendor_Invoices_Q2FY27/Rta_Q2FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_B_onshore/Vendor_Invoices_Q2FY27/Trustee_Q1FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_B_onshore/Vendor_Invoices_Q2FY27/Trustee_Q2FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `scheme_B_onshore/Vendor_Invoices_Q2FY27/Valuer_Q2FY27_Invoice.pdf` | Service provider | Quarter close & NAV | journal |
| `shared/Opening_Balances_30Jun26_locked.xlsx` | Fund administrator (audited prior period) | Ledger & TB | period, journal, journal_line, capital_account |
