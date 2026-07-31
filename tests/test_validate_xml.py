import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.lxml_validator import LxmlValidator


def test_accepts_well_formed_xml():
    validator = LxmlValidator()
    validator.validate(b"<Transaction><Ref>ABC123</Ref></Transaction>")


def test_rejects_malformed_xml():
    validator = LxmlValidator()
    with pytest.raises(XmlValidationError) as exc:
        validator.validate(b"<Transaction><Ref>ABC123</Transaction>")
    assert exc.value.problems  # carries at least one problem message


def test_validates_against_xsd(tmp_path):
    xsd = tmp_path / "schema.xsd"
    xsd.write_text(
        """<?xml version="1.0"?>
        <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="Transaction">
            <xs:complexType>
              <xs:sequence>
                <xs:element name="Ref" type="xs:string"/>
              </xs:sequence>
            </xs:complexType>
          </xs:element>
        </xs:schema>"""
    )
    validator = LxmlValidator(xsd_path=xsd)
    validator.validate(b"<Transaction><Ref>ABC123</Ref></Transaction>")

    with pytest.raises(XmlValidationError):
        validator.validate(b"<Transaction><Wrong>x</Wrong></Transaction>")
