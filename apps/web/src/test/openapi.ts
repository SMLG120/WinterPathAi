import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';

const specPath = fileURLToPath(new URL('../../../../docs/contracts/openapi.yaml', import.meta.url));

/** Ajv validator for any `#/components/schemas/<Name>` in the frozen v1 contract. */
export function contractValidator() {
  const doc = parse(readFileSync(specPath, 'utf8')) as Record<string, unknown>;
  const ajv = new Ajv2020({ strict: false, allErrors: true, validateSchema: false });
  addFormats(ajv);
  ajv.addSchema({ ...doc, $id: 'openapi.json' });
  return (name: string, data: unknown): string[] => {
    const validate = ajv.getSchema(`openapi.json#/components/schemas/${name}`);
    if (!validate) throw new Error(`No schema ${name}`);
    return validate(data) ? [] : (validate.errors ?? []).map((e) => `${e.instancePath} ${e.message}`);
  };
}
