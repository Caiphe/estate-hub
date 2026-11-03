"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState, type FormEvent } from "react";

import { RoleCheckboxes } from "@/components/role-checkboxes";
import { Forbidden } from "@/components/status-panels";
import { TextField } from "@/components/text-field";
import { staffApi } from "@/lib/api/staff";
import { useSession } from "@/lib/session";
import {
  PASSWORD_MAX,
  PASSWORD_MIN,
  mapStaffError,
  validateStaffCreate,
  type FieldErrors,
} from "@/lib/staff-forms";
import { useHydrated } from "@/lib/use-hydrated";

export default function NewStaffPage() {
  const { client, permissions } = useSession();
  const api = useMemo(() => staffApi(client), [client]);
  const router = useRouter();
  const hydrated = useHydrated();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<string[]>([]);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  // The API enforces staff:create; this only avoids showing a form that cannot work.
  if (!permissions.includes("staff:create")) return <Forbidden what="staff account creation" />;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validateStaffCreate({ email, fullName, password, roles });
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;

    setPending(true);
    try {
      const created = await api.create({ email: email.trim(), fullName: fullName.trim(), password, roles });
      router.push(`/staff/${created.id}?created=1`);
    } catch (error) {
      const mapped = mapStaffError(error);
      setErrors(mapped.fields);
      setFormError(mapped.message);
      setPending(false);
      if (mapped.message) requestAnimationFrame(() => alertRef.current?.focus());
    } finally {
      // Never keep a password around after it was submitted.
      setPassword("");
    }
  }

  return (
    <section className="panel" aria-labelledby="new-staff-heading">
      <p>
        <Link href="/staff" className="text-link">
          ← Staff
        </Link>
      </p>
      <h1 id="new-staff-heading" className="page-title">
        Add staff member
      </h1>
      <form className="form" method="post" noValidate onSubmit={onSubmit} aria-busy={pending}>
        {formError && (
          <div className="form-error" role="alert" tabIndex={-1} ref={alertRef}>
            {formError}
          </div>
        )}
        <TextField
          id="new-email"
          type="email"
          label="Email"
          autoComplete="off"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={errors.email}
          required
        />
        <TextField
          id="new-name"
          label="Full name"
          autoComplete="off"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          error={errors.fullName}
          required
        />
        <TextField
          id="new-password"
          type="password"
          label="Initial password"
          hint={`${PASSWORD_MIN} to ${PASSWORD_MAX} characters. Share it securely; the person can change it after signing in.`}
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
          required
        />
        <RoleCheckboxes idPrefix="new" value={roles} onChange={setRoles} error={errors.roles} />
        <button type="submit" className="button" disabled={pending || !hydrated}>
          {pending ? "Creating…" : "Create staff member"}
        </button>
      </form>
    </section>
  );
}
