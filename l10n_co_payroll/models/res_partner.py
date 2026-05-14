from odoo import api, fields, models


IDENTIFICATION_TYPE_TO_CARVAJAL_CODE = {
    "rut": "31",
    "id_document": "",
    "id_card": "12",
    "passport": "41",
    "foreign_id_card": "42",
    "external_id": "50",
    "residence_document": "47",
    "PEP": "47",
    "civil_registration": "11",
    "national_citizen_id": "13",
    "niup_id": "91",
    "foreign_colombian_card": "21",
    "foreign_resident_card": "22",
    "diplomatic_card": "",
    "PPT": "48",
    "vat": "50",
}

CARVAJAL_CODE_TO_IDENTIFICATION_TYPES = {
    "11": ["civil_registration"],
    "12": ["id_card"],
    "13": ["national_citizen_id"],
    "21": ["foreign_colombian_card"],
    "22": ["foreign_resident_card"],
    "31": ["rut"],
    "41": ["passport"],
    "42": ["foreign_id_card"],
    "47": ["residence_document", "PEP"],
    "48": ["PPT"],
    "50": ["external_id", "vat"],
    "91": ["niup_id"],
}


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_management = fields.Boolean("Administradora proteccion social")
    management_id = fields.Many2one("res.partner.management", string="Administradora")
    fe_habilitada = fields.Boolean(
        string="Habilitar datos fiscales",
        default=True,
        help="Campo legacy conservado por compatibilidad con la capa colombiana de nomina.",
    )
    fe_nit = fields.Char(
        string="Numero de documento",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_identification",
        store=True,
        readonly=False,
    )
    fe_digito_verificacion = fields.Char(
        string="Digito de verificacion",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_identification",
        store=True,
        readonly=False,
    )
    fe_tipo_documento = fields.Char(
        string="Tipo de documento",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_identification",
        store=True,
        readonly=False,
    )
    fe_primer_nombre = fields.Char(
        string="Primer nombre",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_name_fields",
        store=True,
        readonly=False,
    )
    fe_segundo_nombre = fields.Char(
        string="Segundo nombre",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_name_fields",
        store=True,
        readonly=False,
    )
    fe_primer_apellido = fields.Char(
        string="Primer apellido",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_name_fields",
        store=True,
        readonly=False,
    )
    fe_segundo_apellido = fields.Char(
        string="Segundo apellido",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_name_fields",
        store=True,
        readonly=False,
    )
    fe_razon_social = fields.Char(
        string="Razon social",
        compute="_compute_fe_legacy_fields",
        inverse="_inverse_fe_legacy_name_fields",
        store=True,
        readonly=False,
    )

    @api.depends(
        "commercial_partner_id.country_id",
        "commercial_partner_id.state_id",
        "commercial_partner_id.city_id",
        "country_id",
        "state_id",
        "city_id",
        "is_company",
        "name",
        "street",
        "street2",
        "vat",
        "l10n_latam_identification_type_id",
        "l10n_co_edi_commercial_name",
    )
    def _compute_fe_legacy_fields(self):
        for partner in self:
            split_name = partner._l10n_co_payroll_split_name()
            partner.fe_nit = partner._l10n_co_payroll_get_identification_number()
            partner.fe_digito_verificacion = partner._l10n_co_payroll_get_verification_digit()
            partner.fe_tipo_documento = partner._l10n_co_payroll_get_identification_type_code()
            partner.fe_primer_nombre = split_name["first_name"]
            partner.fe_segundo_nombre = split_name["other_names"]
            partner.fe_primer_apellido = split_name["last_name"]
            partner.fe_segundo_apellido = split_name["second_last_name"]
            partner.fe_razon_social = partner._l10n_co_payroll_get_legal_name()

    def _inverse_fe_legacy_identification(self):
        identification_type_model = self.env["l10n_latam.identification.type"]
        for partner in self:
            if partner.fe_tipo_documento:
                identification_codes = CARVAJAL_CODE_TO_IDENTIFICATION_TYPES.get(partner.fe_tipo_documento, [])
                if identification_codes:
                    identification_type = identification_type_model.search(
                        [("l10n_co_document_code", "in", identification_codes)],
                        limit=1,
                    )
                    if identification_type:
                        partner.l10n_latam_identification_type_id = identification_type

            identification = (partner.fe_nit or "").strip()
            verification_digit = (partner.fe_digito_verificacion or "").strip()
            if not identification:
                partner.vat = False
                continue

            if partner.fe_tipo_documento == "31" and verification_digit:
                partner.vat = f"{identification.split('-')[0]}-{verification_digit}"
            else:
                partner.vat = identification

    def _inverse_fe_legacy_name_fields(self):
        for partner in self:
            if partner.is_company:
                legal_name = (partner.fe_razon_social or partner.name or "").strip()
                if legal_name:
                    partner.name = legal_name
                    if "l10n_co_edi_commercial_name" in partner._fields:
                        partner.l10n_co_edi_commercial_name = legal_name
                continue

            name_parts = [
                (partner.fe_primer_nombre or "").strip(),
                (partner.fe_segundo_nombre or "").strip(),
                (partner.fe_primer_apellido or "").strip(),
                (partner.fe_segundo_apellido or "").strip(),
            ]
            partner.name = " ".join(part for part in name_parts if part)

    def _l10n_co_payroll_split_name(self):
        self.ensure_one()
        if self.is_company:
            return {"first_name": "", "other_names": "", "last_name": "", "second_last_name": ""}

        parts = [part for part in (self.name or "").split() if part]
        if len(parts) >= 4:
            return {
                "first_name": parts[0],
                "other_names": " ".join(parts[1:-2]),
                "last_name": parts[-2],
                "second_last_name": parts[-1],
            }
        if len(parts) == 3:
            return {
                "first_name": parts[0],
                "other_names": parts[1],
                "last_name": parts[2],
                "second_last_name": "",
            }
        if len(parts) == 2:
            return {
                "first_name": parts[0],
                "other_names": "",
                "last_name": parts[1],
                "second_last_name": "",
            }
        if len(parts) == 1:
            return {
                "first_name": parts[0],
                "other_names": "",
                "last_name": "",
                "second_last_name": "",
            }
        return {"first_name": "", "other_names": "", "last_name": "", "second_last_name": ""}

    def _l10n_co_payroll_get_identification_number(self):
        self.ensure_one()
        if hasattr(self, "_get_vat_without_verification_code"):
            identification = self._get_vat_without_verification_code()
            if identification:
                return identification.strip()
        return (self.vat or "").strip()

    def _l10n_co_payroll_get_identification_type_code(self):
        self.ensure_one()
        if hasattr(self, "_l10n_co_edi_get_carvajal_code_for_identification_type"):
            code = self._l10n_co_edi_get_carvajal_code_for_identification_type()
            if code is not None:
                return code
        identification_type = self.l10n_latam_identification_type_id.l10n_co_document_code
        return IDENTIFICATION_TYPE_TO_CARVAJAL_CODE.get(identification_type, "")

    def _l10n_co_payroll_get_verification_digit(self):
        self.ensure_one()
        if hasattr(self, "_get_vat_verification_code"):
            digit = self._get_vat_verification_code()
            return "" if digit in (False, None, "", "No aplica") else str(digit)
        return ""

    def _l10n_co_payroll_get_first_name(self):
        self.ensure_one()
        return self._l10n_co_payroll_split_name()["first_name"]

    def _l10n_co_payroll_get_other_names(self):
        self.ensure_one()
        return self._l10n_co_payroll_split_name()["other_names"]

    def _l10n_co_payroll_get_last_names(self):
        self.ensure_one()
        name_parts = self._l10n_co_payroll_split_name()
        return name_parts["last_name"], name_parts["second_last_name"]

    def _l10n_co_payroll_get_legal_name(self):
        self.ensure_one()
        return self.l10n_co_edi_commercial_name or self.name or ""

    def _l10n_co_payroll_get_full_address(self):
        self.ensure_one()
        if hasattr(self, "_l10n_co_edi_get_company_address"):
            return self._l10n_co_edi_get_company_address().strip()
        return " ".join(part for part in [self.street, self.street2] if part).strip()

    def _l10n_co_payroll_get_dian_location_codes(self):
        self.ensure_one()
        country = self.country_id or self.commercial_partner_id.country_id
        state = self.state_id or self.commercial_partner_id.state_id
        city = self.city_id or self.commercial_partner_id.city_id

        state_code = ""
        if state:
            state_code = getattr(state, "l10n_co_edi_code", False) or getattr(state, "state_code", False) or state.code or ""

        city_code = ""
        if city:
            city_code = getattr(city, "l10n_co_edi_code", False) or getattr(city, "code", False) or ""

        return {
            "Pais": str(country.code or "") if country else "",
            "DepartamentoEstado": str(state_code or ""),
            "MunicipioCiudad": str(city_code or ""),
        }
