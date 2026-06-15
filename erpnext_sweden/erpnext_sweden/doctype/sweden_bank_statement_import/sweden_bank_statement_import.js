frappe.ui.form.on("Sweden Bank Statement Import", {
	refresh(frm) {
		frm.disable_save();

		if (frm.doc.status === "Draft" || !frm.doc.status) {
			frm.add_custom_button(__("Parse File"), () => {
				if (!frm.doc.statement_file) {
					frappe.msgprint(__("Please attach a camt.053 XML file first."));
					return;
				}
				frm.call({
					method: "parse_file",
					freeze: true,
					freeze_message: __("Parsing camt.053 file…"),
					callback() {
						frm.reload_doc();
					},
				});
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Parsed" || frm.doc.status === "Partially Imported") {
			frm.add_custom_button(__("Import Transactions"), () => {
				frappe.confirm(
					__(
						"This will create {0} Bank Transaction records. Continue?",
						[frm.doc.transaction_count - (frm.doc.imported_count || 0)]
					),
					() => {
						frm.call({
							method: "import_transactions",
							freeze: true,
							freeze_message: __("Importing transactions…"),
							callback() {
								frm.reload_doc();
							},
						});
					}
				);
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Imported") {
			frm.set_intro(
				__("All {0} transactions imported successfully.", [frm.doc.imported_count]),
				"green"
			);
		}

		if (frm.doc.status === "Error") {
			frm.set_intro(__("An error occurred during parsing. See Import Errors section."), "red");
		}
	},

	statement_file(frm) {
		// Reset status when a new file is attached so user has to re-parse
		if (frm.doc.statement_file && frm.doc.status !== "Draft") {
			frm.set_value("status", "Draft");
			frm.set_value("transactions", []);
		}
	},
});
