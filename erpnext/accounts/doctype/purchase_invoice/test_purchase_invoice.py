# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from __future__ import unicode_literals
import unittest
import frappe
import frappe.model
from frappe.utils import cint, flt, today
import frappe.defaults
from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import set_perpetual_inventory, \
	test_records as pr_test_records
from erpnext.exceptions import InvalidCurrency
from erpnext.stock.doctype.stock_entry.test_stock_entry import get_qty_after_transaction

test_dependencies = ["Item", "Cost Center"]
test_ignore = ["Serial No"]

class TestPurchaseInvoice(unittest.TestCase):
	def test_gl_entries_without_auto_accounting_for_stock(self):
		set_perpetual_inventory(0)
		self.assertTrue(not cint(frappe.defaults.get_global_default("auto_accounting_for_stock")))

		wrapper = frappe.copy_doc(test_records[0])
		wrapper.insert()
		wrapper.submit()
		wrapper.load_from_db()
		dl = wrapper

		expected_gl_entries = {
			"_Test Payable - _TC": [0, 1512.30],
			"_Test Account Cost for Goods Sold - _TC": [1250, 0],
			"_Test Account Shipping Charges - _TC": [100, 0],
			"_Test Account Excise Duty - _TC": [140, 0],
			"_Test Account Education Cess - _TC": [2.8, 0],
			"_Test Account S&H Education Cess - _TC": [1.4, 0],
			"_Test Account CST - _TC": [29.88, 0],
			"_Test Account VAT - _TC": [156.25, 0],
			"_Test Account Discount - _TC": [0, 168.03],
		}
		gl_entries = frappe.db.sql("""select account, debit, credit from `tabGL Entry`
			where voucher_type = 'Purchase Invoice' and voucher_no = %s""", dl.name, as_dict=1)
		for d in gl_entries:
			self.assertEqual([d.debit, d.credit], expected_gl_entries.get(d.account))

	def test_gl_entries_with_auto_accounting_for_stock(self):
		set_perpetual_inventory(1)
		self.assertEqual(cint(frappe.defaults.get_global_default("auto_accounting_for_stock")), 1)

		pi = frappe.copy_doc(test_records[1])
		pi.insert()
		pi.submit()
		
		self.check_gle_for_pi(pi.name)
		
		set_perpetual_inventory(0)

	def test_gl_entries_with_auto_accounting_for_stock_against_pr(self):
		set_perpetual_inventory(1)
		self.assertEqual(cint(frappe.defaults.get_global_default("auto_accounting_for_stock")), 1)

		pr = frappe.copy_doc(pr_test_records[0])
		pr.submit()

		pi = frappe.copy_doc(test_records[1])
		for d in pi.get("items"):
			d.purchase_receipt = pr.name
		pi.insert()
		pi.submit()

		self.check_gle_for_pi(pi.name)

		set_perpetual_inventory(0)

	def check_gle_for_pi(self, pi):
		gl_entries = frappe.db.sql("""select account, debit, credit
			from `tabGL Entry` where voucher_type='Purchase Invoice' and voucher_no=%s
			order by account asc""", pi, as_dict=1)
		self.assertTrue(gl_entries)

		expected_values = dict((d[0], d) for d in [
			["_Test Payable - _TC", 0, 720],
			["Stock Received But Not Billed - _TC", 500.0, 0],
			["_Test Account Shipping Charges - _TC", 100.0, 0],
			["_Test Account VAT - _TC", 120.0, 0],
		])

		for i, gle in enumerate(gl_entries):
			self.assertEquals(expected_values[gle.account][0], gle.account)
			self.assertEquals(expected_values[gle.account][1], gle.debit)
			self.assertEquals(expected_values[gle.account][2], gle.credit)

	def test_gl_entries_with_aia_for_non_stock_items(self):
		set_perpetual_inventory()
		self.assertEqual(cint(frappe.defaults.get_global_default("auto_accounting_for_stock")), 1)

		pi = frappe.copy_doc(test_records[1])
		pi.get("items")[0].item_code = "_Test Non Stock Item"
		pi.get("items")[0].expense_account = "_Test Account Cost for Goods Sold - _TC"
		pi.get("taxes").pop(0)
		pi.get("taxes").pop(1)
		pi.insert()
		pi.submit()

		gl_entries = frappe.db.sql("""select account, debit, credit
			from `tabGL Entry` where voucher_type='Purchase Invoice' and voucher_no=%s
			order by account asc""", pi.name, as_dict=1)
		self.assertTrue(gl_entries)

		expected_values = sorted([
			["_Test Payable - _TC", 0, 620],
			["_Test Account Cost for Goods Sold - _TC", 500.0, 0],
			["_Test Account VAT - _TC", 120.0, 0],
		])

		for i, gle in enumerate(gl_entries):
			self.assertEquals(expected_values[i][0], gle.account)
			self.assertEquals(expected_values[i][1], gle.debit)
			self.assertEquals(expected_values[i][2], gle.credit)
		set_perpetual_inventory(0)

	def test_purchase_invoice_calculation(self):
		pi = frappe.copy_doc(test_records[0])
		pi.insert()
		pi.load_from_db()

		expected_values = [
			["_Test Item Home Desktop 100", 90, 59],
			["_Test Item Home Desktop 200", 135, 177]
		]
		for i, item in enumerate(pi.get("items")):
			self.assertEqual(item.item_code, expected_values[i][0])
			self.assertEqual(item.item_tax_amount, expected_values[i][1])
			self.assertEqual(item.valuation_rate, expected_values[i][2])

		self.assertEqual(pi.base_net_total, 1250)

		# tax amounts
		expected_values = [
			["_Test Account Shipping Charges - _TC", 100, 1350],
			["_Test Account Customs Duty - _TC", 125, 1350],
			["_Test Account Excise Duty - _TC", 140, 1490],
			["_Test Account Education Cess - _TC", 2.8, 1492.8],
			["_Test Account S&H Education Cess - _TC", 1.4, 1494.2],
			["_Test Account CST - _TC", 29.88, 1524.08],
			["_Test Account VAT - _TC", 156.25, 1680.33],
			["_Test Account Discount - _TC", 168.03, 1512.30],
		]

		for i, tax in enumerate(pi.get("taxes")):
			self.assertEqual(tax.account_head, expected_values[i][0])
			self.assertEqual(tax.tax_amount, expected_values[i][1])
			self.assertEqual(tax.total, expected_values[i][2])

	def test_purchase_invoice_with_subcontracted_item(self):
		wrapper = frappe.copy_doc(test_records[0])
		wrapper.get("items")[0].item_code = "_Test FG Item"
		wrapper.insert()
		wrapper.load_from_db()

		expected_values = [
			["_Test FG Item", 90, 59],
			["_Test Item Home Desktop 200", 135, 177]
		]
		for i, item in enumerate(wrapper.get("items")):
			self.assertEqual(item.item_code, expected_values[i][0])
			self.assertEqual(item.item_tax_amount, expected_values[i][1])
			self.assertEqual(item.valuation_rate, expected_values[i][2])

		self.assertEqual(wrapper.base_net_total, 1250)

		# tax amounts
		expected_values = [
			["_Test Account Shipping Charges - _TC", 100, 1350],
			["_Test Account Customs Duty - _TC", 125, 1350],
			["_Test Account Excise Duty - _TC", 140, 1490],
			["_Test Account Education Cess - _TC", 2.8, 1492.8],
			["_Test Account S&H Education Cess - _TC", 1.4, 1494.2],
			["_Test Account CST - _TC", 29.88, 1524.08],
			["_Test Account VAT - _TC", 156.25, 1680.33],
			["_Test Account Discount - _TC", 168.03, 1512.30],
		]

		for i, tax in enumerate(wrapper.get("taxes")):
			self.assertEqual(tax.account_head, expected_values[i][0])
			self.assertEqual(tax.tax_amount, expected_values[i][1])
			self.assertEqual(tax.total, expected_values[i][2])

	def test_purchase_invoice_with_advance(self):
		from erpnext.accounts.doctype.journal_entry.test_journal_entry \
			import test_records as jv_test_records

		jv = frappe.copy_doc(jv_test_records[1])
		jv.insert()
		jv.submit()

		pi = frappe.copy_doc(test_records[0])
		pi.append("advances", {
			"journal_entry": jv.name,
			"jv_detail_no": jv.get("accounts")[0].name,
			"advance_amount": 400,
			"allocated_amount": 300,
			"remarks": jv.remark
		})
		pi.insert()
		pi.submit()
		pi.load_from_db()

		self.assertTrue(frappe.db.sql("""select name from `tabJournal Entry Account`
			where reference_type='Purchase Invoice'
			and reference_name=%s and debit_in_account_currency=300""", pi.name))

		self.assertEqual(pi.outstanding_amount, 1212.30)

		pi.cancel()

		self.assertFalse(frappe.db.sql("""select name from `tabJournal Entry Account`
			where reference_type='Purchase Invoice' and reference_name=%s""", pi.name))

	def test_recurring_invoice(self):
		from erpnext.controllers.tests.test_recurring_document import test_recurring_document
		test_recurring_document(self, test_records)

	def test_total_purchase_cost_for_project(self):
		existing_purchase_cost = frappe.db.sql("""select sum(base_net_amount)
			from `tabPurchase Invoice Item` where project = '_Test Project' and docstatus=1""")
		existing_purchase_cost = existing_purchase_cost and existing_purchase_cost[0][0] or 0

		pi = make_purchase_invoice(currency="USD", conversion_rate=60, project="_Test Project")
		self.assertEqual(frappe.db.get_value("Project", "_Test Project", "total_purchase_cost"),
			existing_purchase_cost + 15000)

		pi1 = make_purchase_invoice(qty=10, project="_Test Project")
		self.assertEqual(frappe.db.get_value("Project", "_Test Project", "total_purchase_cost"),
			existing_purchase_cost + 15500)

		pi1.cancel()
		self.assertEqual(frappe.db.get_value("Project", "_Test Project", "total_purchase_cost"),
			existing_purchase_cost + 15000)

		pi.cancel()
		self.assertEqual(frappe.db.get_value("Project", "_Test Project", "total_purchase_cost"), existing_purchase_cost)

	def test_return_purchase_invoice(self):
		set_perpetual_inventory()

		pi = make_purchase_invoice()

		return_pi = make_purchase_invoice(is_return=1, return_against=pi.name, qty=-2)


		# check gl entries for return
		gl_entries = frappe.db.sql("""select account, debit, credit
			from `tabGL Entry` where voucher_type=%s and voucher_no=%s
			order by account desc""", ("Purchase Invoice", return_pi.name), as_dict=1)

		self.assertTrue(gl_entries)

		expected_values = {
			"Creditors - _TC": [100.0, 0.0],
			"Stock Received But Not Billed - _TC": [0.0, 100.0],
		}

		for gle in gl_entries:
			self.assertEquals(expected_values[gle.account][0], gle.debit)
			self.assertEquals(expected_values[gle.account][1], gle.credit)

		set_perpetual_inventory(0)

	def test_multi_currency_gle(self):
		set_perpetual_inventory(0)

		pi = make_purchase_invoice(supplier="_Test Supplier USD", credit_to="_Test Payable USD - _TC",
			currency="USD", conversion_rate=50)

		gl_entries = frappe.db.sql("""select account, account_currency, debit, credit,
			debit_in_account_currency, credit_in_account_currency
			from `tabGL Entry` where voucher_type='Purchase Invoice' and voucher_no=%s
			order by account asc""", pi.name, as_dict=1)

		self.assertTrue(gl_entries)

		expected_values = {
			"_Test Payable USD - _TC": {
				"account_currency": "USD",
				"debit": 0,
				"debit_in_account_currency": 0,
				"credit": 12500,
				"credit_in_account_currency": 250
			},
			"_Test Account Cost for Goods Sold - _TC": {
				"account_currency": "INR",
				"debit": 12500,
				"debit_in_account_currency": 12500,
				"credit": 0,
				"credit_in_account_currency": 0
			}
		}

		for field in ("account_currency", "debit", "debit_in_account_currency", "credit", "credit_in_account_currency"):
			for i, gle in enumerate(gl_entries):
				self.assertEquals(expected_values[gle.account][field], gle[field])


		# Check for valid currency
		pi1 = make_purchase_invoice(supplier="_Test Supplier USD", credit_to="_Test Payable USD - _TC",
			do_not_save=True)

		self.assertRaises(InvalidCurrency, pi1.save)

		# cancel
		pi.cancel()

		gle = frappe.db.sql("""select name from `tabGL Entry`
			where voucher_type='Sales Invoice' and voucher_no=%s""", pi.name)

		self.assertFalse(gle)
	
	def test_purchase_invoice_update_stock_gl_entry_with_perpetual_inventory(self):
		set_perpetual_inventory()
		
		pi = make_purchase_invoice(update_stock=1, posting_date=frappe.utils.nowdate(), 
			posting_time=frappe.utils.nowtime())
		
		gl_entries = frappe.db.sql("""select account, account_currency, debit, credit,
			debit_in_account_currency, credit_in_account_currency
			from `tabGL Entry` where voucher_type='Purchase Invoice' and voucher_no=%s
			order by account asc""", pi.name, as_dict=1)

		self.assertTrue(gl_entries)
		
		expected_gl_entries = dict((d[0], d) for d in [
			[pi.credit_to, 0.0, 250.0],
			[pi.items[0].warehouse, 250.0, 0.0]
		])
		
		for i, gle in enumerate(gl_entries):
			self.assertEquals(expected_gl_entries[gle.account][0], gle.account)
			self.assertEquals(expected_gl_entries[gle.account][1], gle.debit)
			self.assertEquals(expected_gl_entries[gle.account][2], gle.credit)
			
	def test_purchase_invoice_for_is_paid_and_update_stock_gl_entry_with_perpetual_inventory(self):
		set_perpetual_inventory()
		pi = make_purchase_invoice(update_stock=1, posting_date=frappe.utils.nowdate(), 
			posting_time=frappe.utils.nowtime(), cash_bank_account="Cash - _TC", is_paid=1)

		gl_entries = frappe.db.sql("""select account, account_currency, sum(debit) as debit, 
				sum(credit) as credit, debit_in_account_currency, credit_in_account_currency 
			from `tabGL Entry` where voucher_type='Purchase Invoice' and voucher_no=%s 
			group by account, voucher_no order by account asc;""", pi.name, as_dict=1)

		self.assertTrue(gl_entries)
		
		expected_gl_entries = dict((d[0], d) for d in [
			[pi.credit_to, 250.0, 250.0],
			[pi.items[0].warehouse, 250.0, 0.0],
			["Cash - _TC", 0.0, 250.0]
		])
				
		for i, gle in enumerate(gl_entries):
			self.assertEquals(expected_gl_entries[gle.account][0], gle.account)
			self.assertEquals(expected_gl_entries[gle.account][1], gle.debit)
			self.assertEquals(expected_gl_entries[gle.account][2], gle.credit)
	
	def test_update_stock_and_purchase_return(self):
		actual_qty_0 = get_qty_after_transaction()
		
		pi = make_purchase_invoice(update_stock=1, posting_date=frappe.utils.nowdate(),
			posting_time=frappe.utils.nowtime())
		
		actual_qty_1 = get_qty_after_transaction()
		self.assertEquals(actual_qty_0 + 5, actual_qty_1)

		# return entry
		pi1 = make_purchase_invoice(is_return=1, return_against=pi.name, qty=-2, rate=50, update_stock=1)

		actual_qty_2 = get_qty_after_transaction()
		self.assertEquals(actual_qty_1 - 2, actual_qty_2)
		
		pi1.cancel()
		self.assertEquals(actual_qty_1, get_qty_after_transaction())
		
		pi.cancel()
		self.assertEquals(actual_qty_0, get_qty_after_transaction())
		
	def test_subcontracting_via_purchase_invoice(self):
		from erpnext.stock.doctype.stock_entry.test_stock_entry import make_stock_entry
		
		make_stock_entry(item_code="_Test Item", target="_Test Warehouse 1 - _TC", qty=100, basic_rate=100)
		make_stock_entry(item_code="_Test Item Home Desktop 100", target="_Test Warehouse 1 - _TC", 
			qty=100, basic_rate=100)
		
		pi = make_purchase_invoice(item_code="_Test FG Item", qty=10, rate=500, 
			update_stock=1, is_subcontracted="Yes")
		
		self.assertEquals(len(pi.get("supplied_items")), 2)
		
		rm_supp_cost = sum([d.amount for d in pi.get("supplied_items")])
		self.assertEquals(pi.get("items")[0].rm_supp_cost, flt(rm_supp_cost, 2))
		
	def test_rejected_serial_no(self):
		pi = make_purchase_invoice(item_code="_Test Serialized Item With Series", received_qty=2, qty=1,
			rejected_qty=1, rate=500, update_stock=1,
			rejected_warehouse = "_Test Rejected Warehouse - _TC")
		
		self.assertEquals(frappe.db.get_value("Serial No", pi.get("items")[0].serial_no, "warehouse"),
			pi.get("items")[0].warehouse)
			
		self.assertEquals(frappe.db.get_value("Serial No", pi.get("items")[0].rejected_serial_no, 
			"warehouse"), pi.get("items")[0].rejected_warehouse)

def make_purchase_invoice(**args):
	pi = frappe.new_doc("Purchase Invoice")
	args = frappe._dict(args)
	pi.posting_date = args.posting_date or today()
	if args.posting_time:
		pi.posting_time = args.posting_time
	if args.update_stock:
		pi.update_stock = 1
	if args.is_paid:
		pi.is_paid = 1
		
	if args.cash_bank_account:
		pi.cash_bank_account=args.cash_bank_account
		
	pi.company = args.company or "_Test Company"
	pi.supplier = args.supplier or "_Test Supplier"
	pi.currency = args.currency or "INR"
	pi.conversion_rate = args.conversion_rate or 1
	pi.is_return = args.is_return
	pi.return_against = args.return_against
	pi.is_subcontracted = args.is_subcontracted or "No"
	pi.supplier_warehouse = "_Test Warehouse 1 - _TC"

	pi.append("items", {
		"item_code": args.item or args.item_code or "_Test Item",
		"warehouse": args.warehouse or "_Test Warehouse - _TC",
		"qty": args.qty or 5,
		"received_qty": args.received_qty or 0,
		"rejected_qty": args.rejected_qty or 0,
		"rate": args.rate or 50,
		"conversion_factor": 1.0,
		"serial_no": args.serial_no,
		"stock_uom": "_Test UOM",
		"cost_center": "_Test Cost Center - _TC",
		"project": args.project,
		"rejected_warehouse": args.rejected_warehouse or "",
		"rejected_serial_no": args.rejected_serial_no or ""
	})
	if not args.do_not_save:
		pi.insert()
		if not args.do_not_submit:
			pi.submit()
	return pi

test_records = frappe.get_test_records('Purchase Invoice')
