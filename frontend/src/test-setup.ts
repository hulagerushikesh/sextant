/**
 * Unmount between tests. Without it a `getByText` can match a node the
 * previous test rendered, and the failing assertion is in the test that comes
 * after the one that broke.
 *
 * Explicit rather than automatic: `@testing-library/react` registers its own
 * `afterEach` only when the runner exposes globals, and this config does not --
 * tests import `describe`/`it`/`expect` from `vitest` by name, so `tsc -b`
 * type-checks them against the real signatures instead of ambient ones.
 */
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)
