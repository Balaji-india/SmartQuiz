"use client";

import { useState, type FormEvent } from "react";
import { useLoad, useMe } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, Card, ErrorBox, Hash, Loading } from "@/components/ui";
import { BadgeCard } from "@/components/badges";
import { listBadges, listDocuments, setWallet } from "@/lib/api";
import type { BadgeOut, DocumentOut, User } from "@/lib/types";

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

function WalletForm({ me, onSaved }: { me: User; onSaved: (u: User) => void }) {
  const [value, setValue] = useState(me.wallet_address ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const save = async (address: string | null) => {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const u = await setWallet(address);
      setValue(u.wallet_address ?? "");
      setSaved(u.wallet_address ? "Saved. New badges go to this address." : "Cleared. New badges go to your custodial address.");
      onSaved(u);
    } catch (e) {
      setError((e as Error).message); // e.g. "wallet_address has an invalid EIP-55 checksum"
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = value.trim();
    if (!ADDRESS.test(v)) {
      setError("A wallet address is 0x followed by 40 hex characters.");
      return;
    }
    save(v);
  };

  return (
    <Card>
      <h2 className="text-lg font-semibold">Wallet for badges</h2>
      <p className="mt-1 text-sm text-muted">
        Your concept badges are minted to this address on Polygon Amoy. You need no POL: the SmartQuiz issuer pays the gas. Only the address goes on chain,
        never your name or email.
      </p>
      {me.wallet_address ? (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded-full bg-ok-soft px-2.5 py-0.5 text-xs font-semibold text-ok">Wallet set</span>
          <Hash value={me.wallet_address} />
        </p>
      ) : (
        <div className="mt-3 rounded-lg border-l-4 border-accent bg-paper px-3 py-2 text-sm">
          <p className="font-semibold">No wallet: badges use a custodial address</p>
          <p className="mt-0.5 text-muted">
            The server derives an address just for you and holds the badge there. Nobody signs with it, and you can add your own wallet at any time; badges
            already minted stay where they are (they are soulbound).
          </p>
        </div>
      )}
      <form onSubmit={submit} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="0x… (MetaMask account address)"
          spellCheck={false}
          autoComplete="off"
          aria-label="Wallet address"
          className="min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-2.5 font-mono text-sm outline-none focus:border-accent"
        />
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save address"}
        </Button>
        {me.wallet_address && (
          <Button type="button" variant="ghost" disabled={busy} onClick={() => save(null)}>
            Remove
          </Button>
        )}
      </form>
      <p className="mt-2 text-xs text-muted">Paste it exactly as your wallet shows it: a mixed-case address must have a valid checksum (EIP-55).</p>
      {error && (
        <div className="mt-3">
          <ErrorBox message={error} />
        </div>
      )}
      {saved && <p className="mt-3 text-sm font-semibold text-ok">{saved}</p>}
    </Card>
  );
}

function Profile() {
  const { data: me, error, reload, setData } = useMe();
  const { data: badges, error: badgesError, reload: reloadBadges } = useLoad<BadgeOut[]>(listBadges, "badges");
  const { data: docs } = useLoad<DocumentOut[]>(listDocuments, "docs");

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!me) return <Loading label="Loading your profile…" />;
  const filename = (id: string) => docs?.find((d) => d.id === id)?.filename;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Profile</h1>
        <p className="mt-1 text-muted">
          {me.name} · {me.email} · <span className="capitalize">{me.role}</span>
        </p>
      </div>

      <WalletForm me={me} onSaved={setData} />

      <section>
        <h2 className="text-lg font-semibold">My badges</h2>
        <p className="mt-1 text-sm text-muted">One soulbound badge per mastered concept. Claim them on a document&apos;s Mastery page.</p>
        {badgesError && (
          <div className="mt-3">
            <ErrorBox message={badgesError} onRetry={reloadBadges} />
          </div>
        )}
        {!badges && !badgesError && <Loading label="Loading badges…" />}
        {badges && badges.length === 0 && (
          <Card className="mt-3">
            <p className="text-sm text-muted">No badges yet. Reach 95% mastery on a concept, then press Claim badge on the Mastery page.</p>
          </Card>
        )}
        {badges && badges.length > 0 && (
          <ul className="mt-3 grid gap-4 md:grid-cols-2">
            {badges.map((b) => (
              <BadgeCard key={b.id} badge={b} subtitle={filename(b.document_id)} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export function ProfileView() {
  return (
    <AuthedPage>
      <Profile />
    </AuthedPage>
  );
}
