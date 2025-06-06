**Use Case Template** 

 

 **Identification** 

**Use Case ID:** UC-AP-001 

**Module Group:** Accounts Payable 

**Legacy Program Ref:** AP100.RPG 

**Version**: 1.0 

**Last Update:** 3.5.2025 

**Last Update By:** Jeremy Callinan (AI) 

**Created:**  2.13.2025 

**Created By:** Jeremy Callinan (AI) 

**Description:**   
   
This use case describes the process of creating a new voucher transaction within the **AP** system. The process involves capturing vendor information, invoice details, and validation of financial data before committing the transaction to the system. 

 

**Pre-Condition:** 

* Users must have an invoice from a vendor to enter in the system.    
* The vendor must already be set up in the system.   
* Any vendor discounts must already be set up in the system.    
*  Any GL accounts that will be expense to must already be set up in the system. 

 

 

**Post-Condition:** 

* An AP Voucher record is created in the database main and history table.   
* The AP Voucher is set to Open.    
* The AP General Ledger account in increased by that invoice.    
* The expense GL associated with this invoice balance is increased.  

**Entities Used / Tables Used:** 

 

**Program Steps:** 

 

**Tests Needed:** 

 

 

 

