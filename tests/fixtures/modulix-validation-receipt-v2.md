# ModuLix receipt wire fixture

`modulix-validation-receipt-v2.compact.json` is the unmodified output of the
real `receipt` CLI in
[`collection_candidate_receiver.py` at 7c333e54](https://github.com/lightning-it/modulix-validation/blob/7c333e54bcf07e39b7091b42de4c01f78b95da17/scripts/collection_candidate_receiver.py),
using the same revision of `collection_candidate_request.py`.

It was generated offline in the digest-pinned Devtools container using the
synthetic request/run/job identities from `test_modulix_validation_receipt.py`.
The producer run was in progress; the four required validation jobs were
successful and the signing job was in progress. The actual CLI validated these
inputs and wrote the compact sorted JSON plus its trailing newline. No signing,
network, credentials or infrastructure were used.

The consumer's fake download copies these exact bytes. The regression verifies
that signature verification and the persisted receipt receive the same bytes,
while noncanonical reencoding, duplicate keys and non-JSON constants fail.
