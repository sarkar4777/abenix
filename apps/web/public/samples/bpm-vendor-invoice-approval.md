# SOP: Vendor Invoice Approval (Accounts Payable)

Owner: Finance Operations
Version: 3.2
Volume: about 4,000 invoices a month, 70% under 5,000 USD

## Lanes

- Accounts Payable (AP) clerk
- AP automation (OCR and ERP)
- Budget owner (the department that ordered the goods)
- Treasury
- Internal Audit (sample checks only)

## Trigger

A vendor invoice arrives as a PDF by email to ap-inbox@, through the supplier portal, or on paper by post.

## Steps

1. **Receive invoice** (AP automation). Emails and portal uploads land in the AP queue. Paper invoices are scanned by the mailroom within 1 business day.
2. **Extract invoice data** (AP automation). OCR reads vendor name, vendor tax ID, invoice number, invoice date, due date, currency, line items, tax and total.
3. **Check for duplicates** (AP automation). Same vendor, same invoice number, or same amount within 30 days is flagged as a possible duplicate.
4. **Validate vendor** (AP clerk). The vendor must exist in the vendor master with verified bank details. New or changed bank details go to step 4a.
   - 4a. **Bank detail change verification** (Treasury). Call the vendor on the phone number held in the vendor master, never the number on the invoice. Record the call in the vendor file.
5. **Match to purchase order** (AP clerk). Three-way match: invoice, purchase order and goods receipt. Tolerance is 2% or 100 USD, whichever is lower.
   - Decision: **Match within tolerance?**
     - Yes: go to step 7.
     - No: go to step 6.
6. **Resolve exception** (AP clerk with budget owner). Common causes are price differences, partial deliveries, missing goods receipt, and invoices without a PO. The clerk emails the budget owner with the discrepancy. Budget owners must answer within 3 business days, otherwise the exception escalates to their manager.
7. **Code the invoice** (AP clerk). Assign GL account, cost center and tax code. Non-PO invoices use the coding guide, which is a 40-page PDF that clerks often get wrong for software subscriptions and travel.
8. **Approve** (budget owner). Approval limits:
   - under 5,000 USD: budget owner
   - 5,000 to 50,000 USD: budget owner and department head
   - over 50,000 USD: plus the CFO
   - Decision: **Approved?** If rejected, the invoice returns to the AP clerk with a reason and the vendor is contacted.
9. **Schedule payment** (Treasury). Pay on the due date, or early when the vendor offers a discount of at least 1% for payment within 10 days.
10. **Pay and post** (AP automation). Payment run twice a week. The ERP posts the payment and closes the invoice.
11. **Audit sample** (Internal Audit). Each month 2% of paid invoices are sampled and re-checked against this SOP. Findings go to the Finance Operations lead.

## Service levels

- Invoice received to approved: 5 business days
- Exceptions resolved: 3 business days
- Late payment penalties last year: 180,000 USD, mostly from exceptions that waited on budget owners

## Known pain points

- Clerks spend about 40% of their time on exceptions and chasing budget owners.
- Coding of non-PO invoices is inconsistent and causes month-end reclasses.
- Two bank detail fraud attempts were caught last year, one only at the audit sample.
- Vendors email AP asking "when will I be paid" about 600 times a month.
