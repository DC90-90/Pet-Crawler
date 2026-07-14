import { useState } from "react";
import { Modal, Button, NumberField, Label, Select, ListBox, Switch, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useRecommendTours } from "@/lib/queries";
import { TourCard } from "./TourCard";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ACTIVITY = ["relaxed", "moderate", "active", "challenging"];

export function HelpMeChoose({
  isOpen,
  onOpenChange,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const recommend = useRecommendTours();
  const [days, setDays] = useState(3);
  const [month, setMonth] = useState("Jul");
  const [groupSize, setGroupSize] = useState(2);
  const [children, setChildren] = useState(false);
  const [activity, setActivity] = useState("moderate");
  const [transport, setTransport] = useState(false);

  const submit = () => {
    recommend.mutate({ days, month, groupSize, children, activityLevel: activity, needTransport: transport });
  };

  const results = recommend.data?.items ?? [];

  return (
    <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Backdrop>
        <Modal.Container>
          <Modal.Dialog className="max-w-2xl">
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>{t("actions.helpMeChoose")}</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              {results.length === 0 ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  <NumberField value={days} onChange={setDays} minValue={1} maxValue={30}>
                    <Label>Number of days</Label>
                    <NumberField.Group>
                      <NumberField.DecrementButton />
                      <NumberField.Input />
                      <NumberField.IncrementButton />
                    </NumberField.Group>
                  </NumberField>

                  <Select selectedKey={month} onSelectionChange={(k) => setMonth(String(k))}>
                    <Label>Month of travel</Label>
                    <Select.Trigger>
                      <Select.Value />
                      <Select.Indicator />
                    </Select.Trigger>
                    <Select.Popover>
                      <ListBox>
                        {MONTHS.map((m) => (
                          <ListBox.Item key={m} id={m}>{m}</ListBox.Item>
                        ))}
                      </ListBox>
                    </Select.Popover>
                  </Select>

                  <NumberField value={groupSize} onChange={setGroupSize} minValue={1} maxValue={20}>
                    <Label>{t("inquiry.groupSize")}</Label>
                    <NumberField.Group>
                      <NumberField.DecrementButton />
                      <NumberField.Input />
                      <NumberField.IncrementButton />
                    </NumberField.Group>
                  </NumberField>

                  <Select selectedKey={activity} onSelectionChange={(k) => setActivity(String(k))}>
                    <Label>{t("inquiry.activityLevel")}</Label>
                    <Select.Trigger>
                      <Select.Value />
                      <Select.Indicator />
                    </Select.Trigger>
                    <Select.Popover>
                      <ListBox>
                        {ACTIVITY.map((a) => (
                          <ListBox.Item key={a} id={a} className="capitalize">{a}</ListBox.Item>
                        ))}
                      </ListBox>
                    </Select.Popover>
                  </Select>

                  <Switch isSelected={children} onChange={setChildren}>
                    <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>Traveling with children</Switch.Content>
                  </Switch>
                  <Switch isSelected={transport} onChange={setTransport}>
                    <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{t("inquiry.needTransport")}</Switch.Content>
                  </Switch>
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  {results.slice(0, 4).map((tour) => (
                    <TourCard key={tour.id} tour={tour} />
                  ))}
                </div>
              )}
            </Modal.Body>
            <Modal.Footer>
              {results.length === 0 ? (
                <Button variant="primary" onPress={submit} isDisabled={recommend.isPending}>
                  {recommend.isPending ? <Spinner /> : "Suggest tours"}
                </Button>
              ) : (
                <Button variant="secondary" onPress={() => recommend.reset()}>
                  Start over
                </Button>
              )}
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
