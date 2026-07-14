import { useEffect, useState } from "react";
import { Button, Separator } from "@heroui/react";
import { useNavigationAdmin, useUpdateNavigation, errMessage } from "@/lib/admin";
import type { Navigation, NavLink, LocalizedText } from "@/lib/types";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LoadingState, ErrorState } from "@/components/admin/AdminEmptyState";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { FormCard, TextInput } from "@/components/admin/FormField";

const EMPTY: Navigation = { mainMenu: [], footerGroups: [] };

export function Component() {
  const { data, isLoading, isError, error } = useNavigationAdmin();
  const update = useUpdateNavigation();
  const [nav, setNav] = useState<Navigation>(EMPTY);

  useEffect(() => {
    if (data) setNav({ ...EMPTY, ...data });
  }, [data]);

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={errMessage(error)} />;

  const setMenuItem = (i: number, patch: Partial<NavLink>) =>
    setNav((n) => ({
      ...n,
      mainMenu: n.mainMenu.map((m, idx) => (idx === i ? { ...m, ...patch } : m)),
    }));

  return (
    <div>
      <AdminPageHeader
        title="Navigation"
        description="Main menu, footer groups, social and legal links."
        actions={
          <Button
            variant="primary"
            size="sm"
            onPress={() => update.mutate(nav)}
            isDisabled={update.isPending}
          >
            {update.isPending ? "Saving…" : "Save"}
          </Button>
        }
      />

      <div className="flex flex-col gap-6">
        {/* Main menu */}
        <FormCard title="Main menu">
          {nav.mainMenu.map((item, i) => (
            <div key={i} className="flex items-start gap-2 rounded-lg border border-border p-3">
              <div className="grid flex-1 gap-3 sm:grid-cols-2">
                <LocalizedInput
                  label="Label"
                  value={item.label}
                  onChange={(v) => setMenuItem(i, { label: v })}
                />
                <TextInput
                  label="Href"
                  value={item.href}
                  onChange={(v) => setMenuItem(i, { href: v })}
                  placeholder="/tours"
                />
              </div>
              <Button
                variant="tertiary"
                size="sm"
                aria-label="Remove menu item"
                onPress={() =>
                  setNav((n) => ({
                    ...n,
                    mainMenu: n.mainMenu.filter((_, idx) => idx !== i),
                  }))
                }
              >
                ✕
              </Button>
            </div>
          ))}
          <div>
            <Button
              variant="outline"
              size="sm"
              onPress={() =>
                setNav((n) => ({
                  ...n,
                  mainMenu: [...n.mainMenu, { label: { en: "" }, href: "" }],
                }))
              }
            >
              Add menu item
            </Button>
          </div>
        </FormCard>

        {/* Footer groups */}
        <FormCard title="Footer groups">
          {nav.footerGroups.map((group, gi) => (
            <div key={gi} className="rounded-lg border border-border p-3">
              <div className="flex items-start gap-2">
                <div className="flex-1">
                  <LocalizedInput
                    label="Group title"
                    value={group.title}
                    onChange={(v) =>
                      setNav((n) => ({
                        ...n,
                        footerGroups: n.footerGroups.map((g, idx) =>
                          idx === gi ? { ...g, title: v } : g,
                        ),
                      }))
                    }
                  />
                </div>
                <Button
                  variant="tertiary"
                  size="sm"
                  aria-label="Remove group"
                  onPress={() =>
                    setNav((n) => ({
                      ...n,
                      footerGroups: n.footerGroups.filter((_, idx) => idx !== gi),
                    }))
                  }
                >
                  ✕
                </Button>
              </div>
              <Separator className="my-3" />
              <div className="flex flex-col gap-2">
                {group.links.map((link, li) => (
                  <div key={li} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                    <LocalizedInput
                      label="Link label"
                      value={link.label}
                      onChange={(v: LocalizedText) =>
                        setNav((n) => ({
                          ...n,
                          footerGroups: n.footerGroups.map((g, idx) =>
                            idx === gi
                              ? {
                                  ...g,
                                  links: g.links.map((l, lidx) =>
                                    lidx === li ? { ...l, label: v } : l,
                                  ),
                                }
                              : g,
                          ),
                        }))
                      }
                    />
                    <TextInput
                      label="Href"
                      value={link.href}
                      onChange={(v) =>
                        setNav((n) => ({
                          ...n,
                          footerGroups: n.footerGroups.map((g, idx) =>
                            idx === gi
                              ? {
                                  ...g,
                                  links: g.links.map((l, lidx) =>
                                    lidx === li ? { ...l, href: v } : l,
                                  ),
                                }
                              : g,
                          ),
                        }))
                      }
                    />
                    <div className="flex items-end">
                      <Button
                        variant="tertiary"
                        size="sm"
                        aria-label="Remove link"
                        onPress={() =>
                          setNav((n) => ({
                            ...n,
                            footerGroups: n.footerGroups.map((g, idx) =>
                              idx === gi
                                ? { ...g, links: g.links.filter((_, lidx) => lidx !== li) }
                                : g,
                            ),
                          }))
                        }
                      >
                        ✕
                      </Button>
                    </div>
                  </div>
                ))}
                <div>
                  <Button
                    variant="outline"
                    size="sm"
                    onPress={() =>
                      setNav((n) => ({
                        ...n,
                        footerGroups: n.footerGroups.map((g, idx) =>
                          idx === gi
                            ? { ...g, links: [...g.links, { label: { en: "" }, href: "" }] }
                            : g,
                        ),
                      }))
                    }
                  >
                    Add link
                  </Button>
                </div>
              </div>
            </div>
          ))}
          <div>
            <Button
              variant="outline"
              size="sm"
              onPress={() =>
                setNav((n) => ({
                  ...n,
                  footerGroups: [...n.footerGroups, { title: { en: "" }, links: [] }],
                }))
              }
            >
              Add footer group
            </Button>
          </div>
        </FormCard>

        {/* Social links */}
        <FormCard title="Social links">
          {(nav.socialLinks ?? []).map((s, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <TextInput
                label="Platform"
                value={s.platform}
                onChange={(v) =>
                  setNav((n) => ({
                    ...n,
                    socialLinks: (n.socialLinks ?? []).map((x, idx) =>
                      idx === i ? { ...x, platform: v } : x,
                    ),
                  }))
                }
              />
              <TextInput
                label="URL"
                value={s.url}
                onChange={(v) =>
                  setNav((n) => ({
                    ...n,
                    socialLinks: (n.socialLinks ?? []).map((x, idx) =>
                      idx === i ? { ...x, url: v } : x,
                    ),
                  }))
                }
              />
              <div className="flex items-end">
                <Button
                  variant="tertiary"
                  size="sm"
                  aria-label="Remove social link"
                  onPress={() =>
                    setNav((n) => ({
                      ...n,
                      socialLinks: (n.socialLinks ?? []).filter((_, idx) => idx !== i),
                    }))
                  }
                >
                  ✕
                </Button>
              </div>
            </div>
          ))}
          <div>
            <Button
              variant="outline"
              size="sm"
              onPress={() =>
                setNav((n) => ({
                  ...n,
                  socialLinks: [...(n.socialLinks ?? []), { platform: "", url: "" }],
                }))
              }
            >
              Add social link
            </Button>
          </div>
        </FormCard>

        {/* Legal links */}
        <FormCard title="Legal links">
          {(nav.legalLinks ?? []).map((l, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <LocalizedInput
                label="Label"
                value={l.label}
                onChange={(v) =>
                  setNav((n) => ({
                    ...n,
                    legalLinks: (n.legalLinks ?? []).map((x, idx) =>
                      idx === i ? { ...x, label: v } : x,
                    ),
                  }))
                }
              />
              <TextInput
                label="Href"
                value={l.href}
                onChange={(v) =>
                  setNav((n) => ({
                    ...n,
                    legalLinks: (n.legalLinks ?? []).map((x, idx) =>
                      idx === i ? { ...x, href: v } : x,
                    ),
                  }))
                }
              />
              <div className="flex items-end">
                <Button
                  variant="tertiary"
                  size="sm"
                  aria-label="Remove legal link"
                  onPress={() =>
                    setNav((n) => ({
                      ...n,
                      legalLinks: (n.legalLinks ?? []).filter((_, idx) => idx !== i),
                    }))
                  }
                >
                  ✕
                </Button>
              </div>
            </div>
          ))}
          <div>
            <Button
              variant="outline"
              size="sm"
              onPress={() =>
                setNav((n) => ({
                  ...n,
                  legalLinks: [...(n.legalLinks ?? []), { label: { en: "" }, href: "" }],
                }))
              }
            >
              Add legal link
            </Button>
          </div>
        </FormCard>

        {/* CTA */}
        <FormCard title="Header CTA button">
          <LocalizedInput
            label="Label"
            value={nav.ctaButton?.label}
            onChange={(v) =>
              setNav((n) => ({
                ...n,
                ctaButton: { label: v, href: n.ctaButton?.href ?? "" },
              }))
            }
          />
          <TextInput
            label="Href"
            value={nav.ctaButton?.href ?? ""}
            onChange={(v) =>
              setNav((n) => ({
                ...n,
                ctaButton: { label: n.ctaButton?.label ?? { en: "" }, href: v },
              }))
            }
          />
        </FormCard>
      </div>
    </div>
  );
}
