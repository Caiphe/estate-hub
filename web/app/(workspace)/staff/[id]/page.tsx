"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState, type FormEvent } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { RoleCheckboxes, roleLabel } from "@/components/role-checkboxes";
import { Forbidden, LoadError, Loading, NotFound } from "@/components/status-panels";
import { TextField } from "@/components/text-field";
import { staffApi, type StaffApi, type StaffMember } from "@/lib/api/staff";
import { useSession } from "@/lib/session";
import {
  mapStaffError,
  removedRoles,
  validateProfile,
  validateRoles,
  type FieldErrors,
} from "@/lib/staff-forms";
import { useRemote } from "@/lib/use-remote";

type Feedback = { kind: "success" | "error"; text: string } | null;

export default function StaffDetailPage() {
  const { id } = useParams<{ id: string }>();
  const created = useSearchParams().get("created") === "1";
  const { client, permissions, user } = useSession();
  const api = useMemo(() => staffApi(client), [client]);
  const [remote, reload] = useRemote(`staff:${id}`, () => api.get(id));
  const [feedback, setFeedback] = useState<Feedback>(
    created ? { kind: "success", text: "Staff member created." } : null,
  );

  if (remote.status === "loading") return <Loading label="Loading staff member…" />;
  if (remote.status === "forbidden") return <Forbidden what="staff accounts" />;
  if (remote.status === "not_found") return <NotFound what="This staff member" />;
  if (remote.status === "error") return <LoadError onRetry={reload} />;

  const member = remote.data;
  const can = (permission: string) => permissions.includes(permission);
  const done = (text: string) => {
    setFeedback({ kind: "success", text });
    reload();
  };
  const failed = (text: string) => setFeedback({ kind: "error", text });

  return (
    <div className="stack">
      <p>
        <Link href="/staff" className="text-link">
          ← Staff
        </Link>
      </p>
      <section className="panel" aria-labelledby="member-heading">
        <h1 id="member-heading" className="page-title">
          {member.fullName}
        </h1>
        {feedback && (
          <div className={feedback.kind === "success" ? "notice" : "form-error"} role={feedback.kind === "success" ? "status" : "alert"}>
            {feedback.text}
          </div>
        )}
        <dl className="details">
          <div>
            <dt>Email</dt>
            <dd>{member.email}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <span className={`status status-${member.status}`}>{member.status}</span>
            </dd>
          </div>
          <div>
            <dt>Roles</dt>
            <dd>{member.roles.map(roleLabel).join(", ") || "None"}</dd>
          </div>
          <div>
            <dt>Last sign-in</dt>
            <dd>{member.lastLoginAt ? new Date(member.lastLoginAt).toLocaleString() : "Never"}</dd>
          </div>
        </dl>
      </section>

      {can("staff:update") && (
        <ProfileForm key={`profile-${member.updatedAt}`} api={api} member={member} onDone={done} />
      )}
      {can("staff:assign_roles") && (
        <RolesForm key={`roles-${member.roles.join()}`} api={api} member={member} onDone={done} onError={failed} />
      )}
      {(can("staff:disable") || can("staff:reactivate") || can("staff:revoke_sessions")) && (
        <AccessActions
          api={api}
          member={member}
          isSelf={member.id === user.id}
          permissions={permissions}
          onDone={done}
          onError={failed}
        />
      )}
    </div>
  );
}

function ProfileForm({
  api,
  member,
  onDone,
}: {
  api: StaffApi;
  member: StaffMember;
  onDone: (text: string) => void;
}) {
  const [email, setEmail] = useState(member.email);
  const [fullName, setFullName] = useState(member.fullName);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validateProfile({ email, fullName });
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    const changes = {
      ...(email.trim().toLowerCase() !== member.email && { email: email.trim() }),
      ...(fullName.trim() !== member.fullName && { fullName: fullName.trim() }),
    };
    if (!Object.keys(changes).length) {
      setFormError("Nothing has changed.");
      return;
    }
    setPending(true);
    try {
      await api.updateProfile(member.id, changes);
      onDone("Profile saved.");
    } catch (error) {
      const mapped = mapStaffError(error);
      setErrors(mapped.fields);
      setFormError(mapped.message);
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="profile-heading">
      <h2 id="profile-heading" className="section-title">
        Profile
      </h2>
      <form className="form" method="post" noValidate onSubmit={onSubmit} aria-busy={pending}>
        {formError && (
          <div className="form-error" role="alert">
            {formError}
          </div>
        )}
        <TextField
          id="profile-name"
          label="Full name"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          error={errors.fullName}
        />
        <TextField
          id="profile-email"
          type="email"
          label="Email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={errors.email}
        />
        <button type="submit" className="button" disabled={pending}>
          {pending ? "Saving…" : "Save profile"}
        </button>
      </form>
    </section>
  );
}

function RolesForm({
  api,
  member,
  onDone,
  onError,
}: {
  api: StaffApi;
  member: StaffMember;
  onDone: (text: string) => void;
  onError: (text: string) => void;
}) {
  const [roles, setRoles] = useState<string[]>(member.roles);
  const [error, setError] = useState<string | undefined>();
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const removing = removedRoles(member.roles, roles);

  async function save() {
    setPending(true);
    try {
      await api.replaceRoles(member.id, roles);
      setConfirming(false);
      onDone("Roles saved. The change applies to their next request.");
    } catch (failure) {
      setConfirming(false);
      const mapped = mapStaffError(failure);
      if (mapped.fields.roles) setError(mapped.fields.roles);
      else onError(mapped.message ?? "The roles could not be saved.");
      setRoles(member.roles);
    } finally {
      setPending(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validateRoles(roles);
    setError(found.roles);
    if (found.roles) return;
    if (removing.length) setConfirming(true);
    else void save();
  }

  return (
    <section className="panel" aria-labelledby="roles-heading">
      <h2 id="roles-heading" className="section-title">
        Roles
      </h2>
      <form className="form" method="post" noValidate onSubmit={onSubmit} aria-busy={pending}>
        <RoleCheckboxes idPrefix="edit" value={roles} onChange={setRoles} error={error} disabled={pending} />
        <button type="submit" className="button" disabled={pending}>
          Save roles
        </button>
      </form>
      <ConfirmDialog
        open={confirming}
        title="Remove roles?"
        confirmLabel="Remove roles"
        pending={pending}
        onConfirm={() => void save()}
        onCancel={() => setConfirming(false)}
      >
        <p>
          {member.fullName} will lose: {removing.map(roleLabel).join(", ")}. Their current access
          tokens stop working immediately.
        </p>
      </ConfirmDialog>
    </section>
  );
}

type Action = "disable" | "reactivate" | "revoke";

function AccessActions({
  api,
  member,
  isSelf,
  permissions,
  onDone,
  onError,
}: {
  api: StaffApi;
  member: StaffMember;
  isSelf: boolean;
  permissions: string[];
  onDone: (text: string) => void;
  onError: (text: string) => void;
}) {
  const [confirming, setConfirming] = useState<Exclude<Action, "reactivate"> | null>(null);
  const [pending, setPending] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const active = member.status === "active";

  async function run(action: Action) {
    setPending(true);
    try {
      if (action === "disable") await api.disable(member.id);
      if (action === "reactivate") await api.reactivate(member.id);
      if (action === "revoke") await api.revokeSessions(member.id);
      onDone(
        action === "disable"
          ? "Account disabled. All of their sessions have ended."
          : action === "reactivate"
            ? "Account reactivated. They must sign in again."
            : "Signed out everywhere.",
      );
    } catch (error) {
      onError(mapStaffError(error).message ?? "The change could not be made.");
    } finally {
      setPending(false);
      setConfirming(null);
      headingRef.current?.focus();
    }
  }

  return (
    <section className="panel" aria-labelledby="access-heading">
      <h2 id="access-heading" className="section-title" tabIndex={-1} ref={headingRef}>
        Access
      </h2>
      <div className="inline">
        {active && permissions.includes("staff:disable") && (
          <button type="button" className="button button-danger" onClick={() => setConfirming("disable")}>
            {isSelf ? "Disable my account" : "Disable account"}
          </button>
        )}
        {!active && permissions.includes("staff:reactivate") && (
          <button type="button" className="button" disabled={pending} onClick={() => void run("reactivate")}>
            Reactivate account
          </button>
        )}
        {permissions.includes("staff:revoke_sessions") && (
          <button type="button" className="button button-secondary" onClick={() => setConfirming("revoke")}>
            Sign out everywhere
          </button>
        )}
      </div>
      <ConfirmDialog
        open={confirming === "disable"}
        title="Disable this account?"
        confirmLabel="Disable account"
        pending={pending}
        onConfirm={() => void run("disable")}
        onCancel={() => setConfirming(null)}
      >
        <p>{member.fullName} will be signed out everywhere and will not be able to sign in.</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirming === "revoke"}
        title="Sign out everywhere?"
        confirmLabel="Sign out everywhere"
        pending={pending}
        onConfirm={() => void run("revoke")}
        onCancel={() => setConfirming(null)}
      >
        <p>Every session for {member.fullName} ends now. They can sign in again.</p>
      </ConfirmDialog>
    </section>
  );
}
