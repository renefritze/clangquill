#include <catch2/catch_test_macros.hpp>

#include "hash/sha256.hpp"

using clangquill::hash::sha256_hex;

TEST_CASE("SHA-256 known-answer vectors", "[hash]") {
  // Standard NIST/RFC test vectors.
  CHECK(sha256_hex("") ==
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  CHECK(sha256_hex("abc") ==
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  CHECK(sha256_hex(
            "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq") ==
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
}

TEST_CASE("SHA-256 is streaming-stable across chunk boundaries", "[hash]") {
  clangquill::hash::Sha256 a;
  a.update("hello ");
  a.update("world");
  clangquill::hash::Sha256 b;
  b.update("hello world");
  CHECK(a.hexdigest() == b.hexdigest());
}

TEST_CASE("hexdigest resets state for reuse", "[hash]") {
  clangquill::hash::Sha256 h;
  h.update("abc");
  CHECK(h.hexdigest() ==
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  // After digesting, the object must behave like a fresh instance.
  CHECK(h.hexdigest() ==
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
}
