import { useState } from "react";
import {
  Button,
  Card,
  Chip,
  Alert,
  Modal,
  Drawer,
  Tabs,
  Table,
  TextField,
  TextArea,
  Label,
  Input,
  Description,
  Checkbox,
  Switch,
  Spinner,
  Skeleton,
  Badge,
  Avatar,
  Tooltip,
} from "@heroui/react";
import { Container, Section, SectionHeading, MediaImage, Stars } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

const SWATCHES = [
  ["Background", "bg-background border border-border"],
  ["Surface", "bg-surface border border-border"],
  ["Accent (alpine)", "bg-accent"],
  ["Copper", "bg-copper"],
  ["Glacier", "bg-glacier"],
  ["Success", "bg-success"],
  ["Warning", "bg-warning"],
  ["Danger", "bg-danger"],
  ["Muted", "bg-muted"],
];

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-12">
      <h2 className="mb-4 font-display text-2xl">{title}</h2>
      <div className="rounded-2xl border border-border bg-surface/40 p-6">{children}</div>
    </section>
  );
}

export function Component() {
  const [modal, setModal] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [checked, setChecked] = useState(true);
  const [on, setOn] = useState(true);

  return (
    <>
      <Seo title="Design System — Svaneti with Georgie" noindex />
      <Section>
        <Container>
          <SectionHeading eyebrow="Development only" title="Design System" intro="HeroUI v3 + the Alpine theme — the building blocks of the site." />

          <Block title="Typography">
            <h1 className="font-display text-5xl">Svaneti, Guided by a Local</h1>
            <h2 className="mt-3 font-display text-3xl">Mestia · Ushguli · Upper Svaneti</h2>
            <p className="mt-3 max-w-2xl text-muted">Body text uses Manrope. Editorial display headings use Fraunces. Georgian (ქართული) and Arabic (العربية) fonts load automatically per language.</p>
          </Block>

          <Block title="Color palette">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              {SWATCHES.map(([name, cls]) => (
                <div key={name}>
                  <div className={`h-16 rounded-xl ${cls}`} />
                  <p className="mt-2 text-sm">{name}</p>
                </div>
              ))}
            </div>
          </Block>

          <Block title="Buttons">
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary">Primary</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="tertiary">Tertiary</Button>
              <Button variant="outline">Outline</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="danger">Danger</Button>
              <Button variant="primary" isDisabled>Disabled</Button>
              <Button variant="primary" size="sm">Small</Button>
              <Button variant="primary" size="lg">Large</Button>
            </div>
          </Block>

          <Block title="Form elements">
            <div className="grid max-w-xl gap-4">
              <TextField>
                <Label>Full name</Label>
                <Input placeholder="Your name" />
                <Description>Helper text goes here.</Description>
              </TextField>
              <TextField isInvalid>
                <Label>Email</Label>
                <Input placeholder="you@example.com" />
                <Description>Invalid state shown.</Description>
              </TextField>
              <TextField>
                <Label>Message</Label>
                <TextArea rows={3} placeholder="Tell Georgie about your trip" />
              </TextField>
              <Checkbox isSelected={checked} onChange={setChecked}>
                <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>I agree to be contacted</Checkbox.Content>
              </Checkbox>
              <Switch isSelected={on} onChange={setOn}>
                <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>Family friendly</Switch.Content>
              </Switch>
            </div>
          </Block>

          <Block title="Cards & image treatments">
            <div className="grid gap-6 sm:grid-cols-3">
              <Card className="overflow-hidden">
                <MediaImage url={undefined} alt="Placeholder gradient" ratio="aspect-[3/2]" />
                <Card.Header>
                  <Card.Title>Koruldi Lakes</Card.Title>
                  <Card.Description className="text-copper">📍 Mestia</Card.Description>
                </Card.Header>
                <Card.Content><p className="text-sm text-muted">Alpine lakes above Mestia with sweeping Caucasus views.</p></Card.Content>
                <Card.Footer><Stars rating={5} /></Card.Footer>
              </Card>
              <Card>
                <Card.Header><Card.Title>Chips & Badges</Card.Title></Card.Header>
                <Card.Content>
                  <div className="flex flex-wrap gap-2">
                    <Chip variant="primary">Primary</Chip>
                    <Chip variant="secondary">Secondary</Chip>
                    <Chip variant="soft">Soft</Chip>
                    <Chip variant="soft" color="success">Published</Chip>
                    <Chip variant="soft" color="warning">Draft</Chip>
                  </div>
                  <div className="mt-4 flex items-center gap-4">
                    <Badge.Anchor>
                      <Avatar><Avatar.Fallback>G</Avatar.Fallback></Avatar>
                      <Badge color="danger">3</Badge>
                    </Badge.Anchor>
                    <Tooltip>
                      <Tooltip.Trigger>
                        <Button variant="secondary" size="sm">Hover me</Button>
                      </Tooltip.Trigger>
                      <Tooltip.Content>A helpful tooltip</Tooltip.Content>
                    </Tooltip>
                  </div>
                </Card.Content>
              </Card>
              <Card>
                <Card.Header><Card.Title>Loading & empty</Card.Title></Card.Header>
                <Card.Content className="space-y-3">
                  <div className="flex items-center gap-2"><Spinner /> <span className="text-sm text-muted">Loading…</span></div>
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-2/3" />
                  <div className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted">Empty state</div>
                </Card.Content>
              </Card>
            </div>
          </Block>

          <Block title="Alerts">
            <div className="grid gap-3">
              <Alert><Alert.Indicator /><Alert.Content><Alert.Title>Informational</Alert.Title><Alert.Description>Seasonal tours are being confirmed.</Alert.Description></Alert.Content></Alert>
              <Alert className="border-success/40"><Alert.Indicator /><Alert.Content><Alert.Title>Published</Alert.Title><Alert.Description>Your banner is live on the homepage.</Alert.Description></Alert.Content></Alert>
              <Alert className="border-danger/40"><Alert.Indicator /><Alert.Content><Alert.Title>Error</Alert.Title><Alert.Description>Something went wrong.</Alert.Description></Alert.Content></Alert>
            </div>
          </Block>

          <Block title="Overlays">
            <div className="flex flex-wrap gap-3">
              <Button variant="primary" onPress={() => setModal(true)}>Open modal</Button>
              <Button variant="secondary" onPress={() => setDrawer(true)}>Open drawer</Button>
            </div>
            <Modal isOpen={modal} onOpenChange={setModal}>
              <Modal.Backdrop><Modal.Container><Modal.Dialog>
                <Modal.CloseTrigger />
                <Modal.Header><Modal.Heading>Confirm publish</Modal.Heading></Modal.Header>
                <Modal.Body><p className="text-muted">Publishing makes this content visible on the public site.</p></Modal.Body>
                <Modal.Footer><Button variant="tertiary" onPress={() => setModal(false)}>Cancel</Button><Button variant="primary" onPress={() => setModal(false)}>Publish</Button></Modal.Footer>
              </Modal.Dialog></Modal.Container></Modal.Backdrop>
            </Modal>
            <Drawer isOpen={drawer} onOpenChange={setDrawer}>
              <Drawer.Backdrop><Drawer.Content><Drawer.Dialog>
                <Drawer.CloseTrigger />
                <Drawer.Header><Drawer.Heading>Filters</Drawer.Heading></Drawer.Header>
                <Drawer.Body><p className="text-muted">Drawer body content.</p></Drawer.Body>
                <Drawer.Footer><Button variant="primary" onPress={() => setDrawer(false)}>Apply</Button></Drawer.Footer>
              </Drawer.Dialog></Drawer.Content></Drawer.Backdrop>
            </Drawer>
          </Block>

          <Block title="Tabs">
            <Tabs defaultSelectedKey="summer">
              <Tabs.ListContainer>
                <Tabs.List aria-label="Seasons">
                  {["spring", "summer", "autumn", "winter"].map((s) => (
                    <Tabs.Tab key={s} id={s} className="capitalize">{s}<Tabs.Indicator /></Tabs.Tab>
                  ))}
                </Tabs.List>
              </Tabs.ListContainer>
              {["spring", "summer", "autumn", "winter"].map((s) => (
                <Tabs.Panel key={s} id={s}><p className="pt-4 text-sm text-muted capitalize">{s} experiences.</p></Tabs.Panel>
              ))}
            </Tabs>
          </Block>

          <Block title="Table">
            <Table>
              <Table.ScrollContainer>
                <Table.Content aria-label="Tours">
                  <Table.Header>
                    <Table.Column>Tour</Table.Column>
                    <Table.Column>Status</Table.Column>
                    <Table.Column>Type</Table.Column>
                  </Table.Header>
                  <Table.Body>
                    <Table.Row>
                      <Table.Cell>Ushguli & Shkhara</Table.Cell>
                      <Table.Cell><Chip size="sm" variant="soft" color="success">Published</Chip></Table.Cell>
                      <Table.Cell>Private</Table.Cell>
                    </Table.Row>
                    <Table.Row>
                      <Table.Cell>Custom Itinerary</Table.Cell>
                      <Table.Cell><Chip size="sm" variant="soft" color="warning">Draft</Chip></Table.Cell>
                      <Table.Cell>Custom</Table.Cell>
                    </Table.Row>
                  </Table.Body>
                </Table.Content>
              </Table.ScrollContainer>
            </Table>
          </Block>
        </Container>
      </Section>
    </>
  );
}
