"""Unit tests for LxmlCatalogParser. No network access.

The canned documents mirror shapes captured from a live Magaya install, and the
assertions target the traps those shapes set:

- `<Currency Code="…">` puts the code in an ATTRIBUTE, and exchange rates come
  at a precision that float would destroy.
- `<Port>` repeats `<Method>`, so one port serves several transport modes.
- `<ChargeDefinition>` nests a whole `<AccountDefinition>` (with its own
  `<Type>`, `<Name>` and `<Currency>`), so direct-children-only parsing is what
  keeps the charge's own fields from being overwritten by the account's.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.catalog_parser import LxmlCatalogParser

_NS = "http://www.magaya.com/XMLSchema/V1"

# Magaya sends non-home rates at ~20 significant digits; Decimal must keep them.
_EUR_RATE = "0.05069297294009104254"

_CURRENCIES = f"""<?xml version="1.0" encoding="utf-8"?>
<Currencies xmlns="{_NS}">
  <Currency Code="EUR">
    <Name>Euro</Name>
    <ExchangeRate>{_EUR_RATE}</ExchangeRate>
    <DecimalPlaces>2</DecimalPlaces>
    <IsHomeCurrency>false</IsHomeCurrency>
  </Currency>
  <Currency Code="MXN">
    <Name>Mexican Peso</Name>
    <ExchangeRate>1.00</ExchangeRate>
    <DecimalPlaces>2</DecimalPlaces>
    <IsHomeCurrency>true</IsHomeCurrency>
  </Currency>
</Currencies>"""

_EVENT_DEFINITIONS = f"""<?xml version="1.0" encoding="utf-8"?>
<EventDefinitions xmlns="{_NS}">
  <EventDefinition>
    <Name>Recolectado</Name>
    <IncludeInTracking>true</IncludeInTracking>
  </EventDefinition>
  <EventDefinition>
    <Name>Internal note</Name>
    <IncludeInTracking>false</IncludeInTracking>
    <Details>Not shown to customers</Details>
  </EventDefinition>
</EventDefinitions>"""

# The second account nests its parent, which nests its own currency.
_ACCOUNT_DEFINITIONS = f"""<?xml version="1.0" encoding="utf-8"?>
<AccountDefinitions xmlns="{_NS}">
  <AccountDefinition>
    <Type>AccountReceivable</Type>
    <Name>Cuentas por cobrar (MXN)</Name>
    <Currency Code="MXN">
      <Name>Mexican Peso</Name>
      <ExchangeRate>1.00</ExchangeRate>
      <DecimalPlaces>2</DecimalPlaces>
      <IsHomeCurrency>true</IsHomeCurrency>
    </Currency>
  </AccountDefinition>
  <AccountDefinition>
    <Type>CostOfGoodsSold</Type>
    <Name>DESCONSOLIDACION</Name>
    <Number>511-024-000</Number>
    <Currency Code="MXN">
      <Name>Mexican Peso</Name>
    </Currency>
    <ParentAccount>
      <Type>CostOfGoodsSold</Type>
      <Name>COSTOS DE VENTA</Name>
      <Number>511-000-000</Number>
      <Currency Code="USD">
        <Name>US Dollar</Name>
      </Currency>
    </ParentAccount>
  </AccountDefinition>
</AccountDefinitions>"""

# The charge's own Type/Currency/Name-ish fields are shadowed by the nested
# account's. Direct-children-only parsing is what keeps them apart.
_CHARGE_DEFINITIONS = f"""<?xml version="1.0" encoding="utf-8"?>
<ChargeDefinitions xmlns="{_NS}">
  <ChargeDefinition>
    <Type>Other</Type>
    <Description>Ganancia Compartida con el Agente - gasto</Description>
    <Code>AGT-COST</Code>
    <AccountDefinition>
      <Type>CostOfGoodsSold</Type>
      <Name>DESCONSOLIDACION</Name>
      <Number>511-024-000</Number>
      <Currency Code="USD">
        <Name>US Dollar</Name>
      </Currency>
    </AccountDefinition>
    <Amount Currency="MXN">1234.56</Amount>
    <Currency Code="MXN">
      <Name>Mexican Peso</Name>
      <IsHomeCurrency>true</IsHomeCurrency>
    </Currency>
    <TaxDefinition>
      <Name>IVA 16%</Name>
    </TaxDefinition>
    <IATACode>IATA-9</IATACode>
    <Enforce3rdPartyBilling>false</Enforce3rdPartyBilling>
  </ChargeDefinition>
</ChargeDefinitions>"""

# DWC serves two modes; TEST-0 serves none (11 of 494 real ports have no method).
_PORTS = f"""<?xml version="1.0" encoding="utf-8"?>
<Ports xmlns="{_NS}">
  <Port Code="DWC">
    <Country Code="AE">UNITED ARAB EMIRATES</Country>
    <Method>Air</Method>
    <Method>Ocean</Method>
    <Name>MAKTOUM</Name>
    <Subdivision>DU</Subdivision>
  </Port>
  <Port Code="NOMODE">
    <Country Code="MX">MEXICO</Country>
    <Name>PUERTO SIN MODO</Name>
    <Remarks>Inland depot</Remarks>
  </Port>
</Ports>"""


@pytest.fixture
def parser() -> LxmlCatalogParser:
    return LxmlCatalogParser()


# -- currencies ------------------------------------------------------------


def test_parses_currency_code_from_attribute(parser: LxmlCatalogParser) -> None:
    eur, mxn = parser.parse_currencies(_CURRENCIES)

    assert eur.code == "EUR"
    assert eur.name == "Euro"
    assert eur.decimal_places == 2
    assert eur.is_home_currency is False
    assert mxn.code == "MXN"
    assert mxn.is_home_currency is True


def test_keeps_full_exchange_rate_precision(parser: LxmlCatalogParser) -> None:
    """A float round-trip would lose digits; the rate must stay exact."""
    eur, _ = parser.parse_currencies(_CURRENCIES)

    assert eur.exchange_rate == Decimal(_EUR_RATE)
    assert str(eur.exchange_rate) == _EUR_RATE


# -- event definitions -----------------------------------------------------


def test_parses_event_definitions_with_optional_details(
    parser: LxmlCatalogParser,
) -> None:
    tracked, internal = parser.parse_event_definitions(_EVENT_DEFINITIONS)

    assert tracked.name == "Recolectado"
    assert tracked.include_in_tracking is True
    assert tracked.details is None
    assert internal.include_in_tracking is False
    assert internal.details == "Not shown to customers"


# -- account definitions ---------------------------------------------------


def test_parses_accounts_and_nests_parent_recursively(
    parser: LxmlCatalogParser,
) -> None:
    receivable, cogs = parser.parse_account_definitions(_ACCOUNT_DEFINITIONS)

    assert receivable.type == "AccountReceivable"
    assert receivable.number is None
    assert receivable.parent_account is None
    assert receivable.currency is not None
    assert receivable.currency.code == "MXN"

    assert cogs.number == "511-024-000"
    assert cogs.parent_account is not None
    assert cogs.parent_account.name == "COSTOS DE VENTA"
    assert cogs.parent_account.number == "511-000-000"
    # The parent carries its OWN currency, not the child's.
    assert cogs.currency is not None and cogs.currency.code == "MXN"
    assert cogs.parent_account.currency is not None
    assert cogs.parent_account.currency.code == "USD"


# -- charge definitions ----------------------------------------------------


def test_nested_account_does_not_shadow_the_charges_own_fields(
    parser: LxmlCatalogParser,
) -> None:
    (charge,) = parser.parse_charge_definitions(_CHARGE_DEFINITIONS)

    # <Type> and <Currency> exist on BOTH the charge and its nested account.
    assert charge.type == "Other"
    assert charge.currency is not None and charge.currency.code == "MXN"
    assert charge.code == "AGT-COST"
    assert charge.description == "Ganancia Compartida con el Agente - gasto"

    assert charge.account_definition is not None
    assert charge.account_definition.type == "CostOfGoodsSold"
    assert charge.account_definition.name == "DESCONSOLIDACION"
    assert charge.account_definition.currency is not None
    assert charge.account_definition.currency.code == "USD"


def test_parses_charge_amount_with_currency_attribute(
    parser: LxmlCatalogParser,
) -> None:
    (charge,) = parser.parse_charge_definitions(_CHARGE_DEFINITIONS)

    assert charge.amount is not None
    assert charge.amount.value == Decimal("1234.56")
    assert charge.amount.unit == "MXN"
    assert charge.tax_definition_name == "IVA 16%"
    assert charge.iata_code == "IATA-9"
    assert charge.enforce_3rd_party_billing is False


def test_empty_custom_charge_definitions_is_an_empty_list(
    parser: LxmlCatalogParser,
) -> None:
    """A client with no custom charges gets an empty root, not an error."""
    empty = f'<?xml version="1.0" encoding="utf-8"?><CustomChargeDefinitions xmlns="{_NS}"/>'

    assert parser.parse_custom_charge_definitions(empty) == []


# -- ports -----------------------------------------------------------------


def test_collects_every_repeated_method_on_a_port(parser: LxmlCatalogParser) -> None:
    dwc, _ = parser.parse_ports(_PORTS)

    assert dwc.code == "DWC"
    assert dwc.name == "MAKTOUM"
    assert dwc.methods == ["Air", "Ocean"]
    assert dwc.country == "UNITED ARAB EMIRATES"
    assert dwc.country_code == "AE"
    assert dwc.subdivision == "DU"


def test_port_without_methods_gets_an_empty_list(parser: LxmlCatalogParser) -> None:
    _, no_mode = parser.parse_ports(_PORTS)

    assert no_mode.methods == []
    assert no_mode.remarks == "Inland depot"
    assert no_mode.subdivision is None


# -- failure modes ---------------------------------------------------------


def test_rejects_a_document_with_the_wrong_root(parser: LxmlCatalogParser) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse_ports(_CURRENCIES)


def test_rejects_malformed_xml(parser: LxmlCatalogParser) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse_currencies("<Currencies><Currency Code='EUR'>")
