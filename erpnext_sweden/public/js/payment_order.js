/**
 * ERPNext Sweden — Payment Order extension
 *
 * Adds a "Generate pain.001 (Sweden)" button on submitted Payment Orders.
 * The button calls the server-side generator, saves the XML as a file
 * attachment, and triggers a browser download.
 */
frappe.ui.form.on("Payment Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		frm.add_custom_button(
			__("Generate pain.001 (Sweden)"),
			() => {
				frappe.call({
					method: "erpnext_sweden.payments.api.generate_pain001",
					args: { payment_order: frm.doc.name },
					freeze: true,
					freeze_message: __("Generating pain.001 XML…"),
					callback(r) {
						if (!r.exc && r.message) {
							const { file_url, filename, transfer_count } = r.message;
							frappe.msgprint(
								__("pain.001 file generated with {0} transfer(s). Downloading…", [transfer_count]),
								__("Success")
							);
							// Trigger download
							const a = document.createElement("a");
							a.href = file_url;
							a.download = filename;
							document.body.appendChild(a);
							a.click();
							document.body.removeChild(a);
							frm.reload_doc();
						}
					},
				});
			},
			__("Sweden")
		);
	},
});
