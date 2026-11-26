"""Password policy checks applied before a password is hashed."""

from src.domain.exceptions import CatalogDomainError


class PasswordCompromisedError(CatalogDomainError):
    """The supplied password appears in the bundled compromised-password list."""


# MVP breach list: high-frequency passwords from public credential dumps.
# A full HIBP k-anonymity integration is tracked as a follow-up task.
COMPROMISED_PASSWORDS: frozenset[str] = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "123123123",
        "11111111",
        "00000000",
        "87654321",
        "qwerty123",
        "qwertyuiop",
        "qwerty1234",
        "1q2w3e4r",
        "1qaz2wsx",
        "zaq12wsx",
        "asdfghjk",
        "asdf1234",
        "zxcvbnm1",
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "passw0rd",
        "p@ssw0rd",
        "p@ssword1",
        "letmein1",
        "letmein123",
        "welcome1",
        "welcome123",
        "admin123",
        "administrator",
        "root1234",
        "toor1234",
        "iloveyou",
        "iloveyou1",
        "sunshine1",
        "princess1",
        "football1",
        "baseball1",
        "superman1",
        "batman123",
        "trustno1",
        "master123",
        "shadow123",
        "monkey123",
        "dragon123",
        "freedom1",
        "whatever1",
        "starwars1",
        "computer1",
        "internet1",
        "samsung1",
        "google123",
        "facebook1",
        "instagram1",
        "telegram1",
        "youtube1",
        "changeme",
        "changeme1",
        "secret123",
        "secretkey",
        "default1",
        "temp1234",
        "test1234",
        "testtest",
        "qazwsxedc",
        "abc12345",
        "abcd1234",
        "a1b2c3d4",
        "loveme123",
        "mypassword",
        "newpassword",
        "oldpassword",
        "user1234",
        "guest1234",
    }
)


def ensure_password_not_compromised(password: str) -> None:
    """Reject passwords present in the bundled compromised-password list."""
    if password.strip().casefold() in COMPROMISED_PASSWORDS:
        raise PasswordCompromisedError("password is compromised")
